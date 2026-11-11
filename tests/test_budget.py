"""Presupuestador y acciones del dashboard. Modelo y procesos siempre simulados."""
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from dashboard.api import actions
from dashboard.api.main import app
from scripts import ingest
from scripts.agent_runner import AgentReply, AgentSpec
from scripts.budget import (ProposalError, _draft_mentions_price, compute_budget, generate_proposal, load_params,
                            validate_extraction)
from tests.conftest import api_body, make_project, mock_client

PARAMS = {
    "version": "test", "calibrated": False, "hourly_rate_usd": 20, "commission": 0.2, "hours_per_day": 5,
    "tasks": {"ga4_setup": {"label": "GA4", "unit": "propiedad", "hours": [2, 4, 8]},
              "landing": {"label": "Landing", "unit": "landing", "hours": [5, 10, 20]}},
}
EXTRACT = AgentSpec("presupuestador", "sonnet", "1", "x")
DRAFT = AgentSpec("redactor-propuestas", "sonnet", "1", "y")
GOOD_EXTRACTION = {"summary": "Medir conversiones", "missing_info": [], "questions": ["¿Qué CMS usas?"],
                   "red_flags": [], "tasks": [{"type": "ga4_setup", "units": 1, "detail": "GA4", "evidence": "GA4"},
                                              {"type": "landing", "units": 2, "detail": "Dos landings"}]}


def draft_text(amount):
    return f"Propuesta para medir conversiones. Precio: {amount} USD en 5 días. " + "Detalle del plan. " * 12


def fake_runner(extraction=GOOD_EXTRACTION, draft=None, calls=None):
    def runner(spec, payload):
        data = json.loads(payload)
        if calls is not None:
            calls.append((spec.name, data))
        if spec.name == "presupuestador":
            body = extraction
        else:
            body = draft if draft is not None else {"language": "es", "proposal": draft_text(data["price"]["amount"])}
        return AgentReply(ok=True, text=json.dumps(body), model="claude-sonnet", cost_usd=0.01)
    return runner


def test_calculo_en_codigo_por_escenario():
    budget = compute_budget(GOOD_EXTRACTION["tasks"], PARAMS, budget_max_usd=500)
    medium = budget["scenarios"]["medio"]
    # 1 x 4 h + 2 x 10 h = 24 h; 24 x 20 = 480 de coste; 480 / 0,8 = 600 de precio.
    assert medium == {"hours": 24, "cost_usd": 480, "price_usd": 600, "margin_usd": -80}
    assert budget["recommended_price_usd"] == 600 and budget["delivery_days"] == 5
    assert budget["scenarios"]["bajo"]["hours"] == 12 and budget["scenarios"]["alto"]["hours"] == 48


def test_tareas_sin_referencia_no_suman():
    tasks = GOOD_EXTRACTION["tasks"] + [{"type": "otro", "units": 3, "detail": "Logo"}]
    assert compute_budget(tasks, PARAMS, None)["scenarios"]["medio"]["hours"] == 24


def test_redondeo_y_sin_presupuesto_del_cliente():
    budget = compute_budget([{"type": "ga4_setup", "units": 1, "detail": "x"}], {**PARAMS, "hourly_rate_usd": 21.5}, None)
    assert budget["recommended_price_usd"] == 110  # 4 x 21,5 / 0,8 = 107,5 -> se redondea hacia arriba a 110
    assert budget["scenarios"]["medio"]["margin_usd"] is None


@pytest.mark.parametrize("change", [
    {"tasks": [{"type": "inventado", "units": 1, "detail": "x"}]},
    {"tasks": [{"type": "landing", "units": 0, "detail": "x"}]},
    {"tasks": [{"type": "landing", "units": True, "detail": "x"}]},
    {"tasks": [{"type": "landing", "units": 1, "detail": ""}]},
    {"questions": "una"}, {"summary": None},
])
def test_extraccion_invalida(change):
    assert validate_extraction({**GOOD_EXTRACTION, **change}, PARAMS["tasks"]) is None


def test_detecta_el_precio_en_el_borrador():
    assert _draft_mentions_price("Mi propuesta es de 1.500 USD", 1500)
    assert _draft_mentions_price("Mi propuesta es de 1,500 USD", 1500)
    assert not _draft_mentions_price("Mi propuesta es de 15000 USD", 1500)


def test_parametros_reales_marcados_como_ejemplo():
    params = load_params()
    assert params["calibrated"] is False and 0 < params["commission"] < 1
    assert all(len(task["hours"]) == 3 for task in params["tasks"].values())


@pytest.fixture
def project_id(conn, config):
    client = mock_client(lambda r: httpx.Response(200, json=api_body([make_project(1)])))
    ingest.run_ingest(conn, "freelancer", client=client, **config())
    conn.commit()
    return conn.execute("SELECT id FROM projects").fetchone()["id"]


def test_genera_y_guarda_presupuesto_y_rentabilidad(conn, project_id):
    calls = []
    row = generate_proposal(conn, project_id, runner=fake_runner(calls=calls), extract_spec=EXTRACT,
                            draft_spec=DRAFT, params=PARAMS)
    assert [c[0] for c in calls] == ["presupuestador", "redactor-propuestas"]
    # El redactor recibe la cifra calculada por el codigo, no la calcula.
    assert calls[1][1]["price"] == {"amount": 600, "currency": "USD"} and calls[1][1]["delivery_days"] == 5
    assert float(row["recommended_price_usd"]) == 600 and row["draft"].startswith("Propuesta")
    assert row["calibrated"] is False and any("ejemplo" in w for w in row["warnings"])
    # El cliente ofrece hasta 750 USD y el precio es 600: no hay aviso de sobreprecio.
    assert not any("supera el presupuesto" in w for w in row["warnings"])
    profit = conn.execute("SELECT * FROM profitability").fetchone()
    assert profit["hours_by_scenario"]["medio"] == 24 and float(profit["commission"]) == 0.2
    assert len(conn.execute("SELECT * FROM agent_calls").fetchall()) == 2


def test_aviso_si_el_borrador_no_usa_el_precio(conn, project_id):
    runner = fake_runner(draft={"language": "es", "proposal": "Propuesta sin cifras. " + "Texto. " * 40})
    row = generate_proposal(conn, project_id, runner=runner, extract_spec=EXTRACT, draft_spec=DRAFT, params=PARAMS)
    assert any("no menciona el precio" in w for w in row["warnings"])


def test_respuesta_invalida_reintenta_y_falla(conn, project_id):
    calls = []
    with pytest.raises(ProposalError):
        generate_proposal(conn, project_id, runner=fake_runner(extraction={"x": 1}, calls=calls),
                          extract_spec=EXTRACT, draft_spec=DRAFT, params=PARAMS)
    assert len(calls) == 2 and conn.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 0


def test_sin_tareas_no_redacta(conn, project_id):
    calls = []
    row = generate_proposal(conn, project_id, runner=fake_runner(extraction={**GOOD_EXTRACTION, "tasks": []}, calls=calls),
                            extract_spec=EXTRACT, draft_spec=DRAFT, params=PARAMS)
    assert [c[0] for c in calls] == ["presupuestador"] and row["draft"] is None


@pytest.fixture
def api(conn, project_id, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    return TestClient(app)


def test_api_presupuesto(api, project_id, monkeypatch):
    from scripts import budget
    monkeypatch.setattr(budget, "generate_proposal", lambda conn, pid: {"project_id": pid, "draft": "ok"})
    assert api.get(f"/api/projects/{project_id}/proposal").json() is None
    response = api.post(f"/api/projects/{project_id}/proposal")
    assert response.status_code == 201 and response.json() == {"project_id": project_id, "draft": "ok"}
    blocked = api.post(f"/api/projects/{project_id}/proposal", headers={"origin": "https://evil.example"})
    assert blocked.status_code == 403
    assert api.get("/api/budget/params").json()["calibrated"] is False


def test_api_lanza_la_ingesta_sin_proceso_real(api, monkeypatch, conn):
    started = []
    monkeypatch.setattr(actions, "start_process", lambda args, **kw: started.append(args))
    assert api.get("/api/pipeline/status").json()["running"] is False
    response = api.post("/api/pipeline/run", json={"full": True})
    assert response.status_code == 202 and started[0][-3:] == ["scripts.pipeline", "freelancer", "--full"]


def test_api_no_lanza_si_ya_hay_una_en_curso(api, monkeypatch, conn):
    from scripts.db import pipeline_lock
    started = []
    monkeypatch.setattr(actions, "start_process", lambda args, **kw: started.append(args))
    with pipeline_lock(conn):
        assert api.get("/api/pipeline/status").json()["running"] is True
        assert api.post("/api/pipeline/run", json={}).status_code == 409
    assert started == []


def test_api_no_lanza_fuentes_sin_permiso(api, monkeypatch, conn):
    monkeypatch.setattr(actions, "start_process", lambda args, **kw: None)
    conn.execute("UPDATE sources SET legal_status = 'pendiente'")
    conn.commit()
    assert api.post("/api/pipeline/run", json={}).status_code == 422
    assert api.post("/api/pipeline/run", json={"source": "upwork"}).status_code == 422
