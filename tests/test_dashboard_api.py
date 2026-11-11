"""Tests de la API del dashboard. El HTTP de la fuente siempre es simulado."""
import os

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from dashboard.api.main import app, confusion_report, read_conn
from scripts import ingest
from tests.conftest import api_body, make_project, mock_client


def test_confusion_report_calcula_precision_y_recall():
    report = confusion_report([("seo", "seo"), ("seo", "otra"), ("otra", "otra"), ("otra", "seo")])
    assert report["n"] == 4 and report["matrix"]["seo"] == {"otra": 1, "seo": 1}
    assert report["per_category"]["seo"] == {"precision": 0.5, "recall": 0.5, "support": 2}


def test_host_externo_rechazado():
    response = TestClient(app, headers={"host": "evil.example"}).get("/api/runs")
    assert response.status_code == 400


@pytest.fixture
def api(conn, config, monkeypatch):
    """Base de pruebas con un proyecto ingerido a traves del flujo real."""
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    cfg = config()
    monkeypatch.setattr(ingest, "SNAPSHOT_DIR", cfg["snapshot_dir"])
    client = mock_client(lambda r: httpx.Response(200, json=api_body([make_project(1)])))
    ingest.run_ingest(conn, "freelancer", client=client, **cfg)
    project_id = conn.execute("SELECT id FROM projects").fetchone()["id"]
    conn.commit()
    return TestClient(app), project_id, conn


def test_salud_y_corridas(api):
    client, _, _ = api
    assert client.get("/api/health").json() == {"status": "ok"}
    run = client.get("/api/runs").json()[0]
    assert run["status"] == "ok" and run["source"] == "freelancer" and run["profile_version"] == 1


def test_bandeja_muestra_procedencia_y_filtra(api):
    client, _, _ = api
    body = client.get("/api/projects").json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["source_run_id"] is not None and item["profile_version"] == 1
    assert item["category"] is None and float(item["budget_usd"]) == 750.0
    assert client.get("/api/projects", params={"min_budget_usd": 1000}).json()["total"] == 0
    assert client.get("/api/projects", params={"category": "sin_clasificar"}).json()["total"] == 1
    assert client.get("/api/projects", params={"category": "seo"}).json()["total"] == 0


def test_auditoria_compara_con_snapshot_sin_exponer_ruta(api):
    client, project_id, _ = api
    body = client.get(f"/api/projects/{project_id}/audit").json()
    assert body["fields"]["title"] == body["original"]["title"] == "Proyecto SEO 1"
    assert "owner_id" not in body["original"] and "file_path" not in body["snapshot"]


def test_snapshot_fuera_de_la_carpeta_no_se_lee(api, tmp_path):
    client, project_id, conn = api
    outside = tmp_path.parent / "fuera.json"
    outside.write_text('{"result": {"projects": [{"id": 1, "title": "secreto"}]}}', encoding="utf-8")
    conn.execute("UPDATE raw_snapshots SET file_path=%s", (str(outside),))
    conn.commit()
    assert client.get(f"/api/projects/{project_id}/audit").json()["original"] is None


def test_etiqueta_incorrecta_guarda_valor_correcto(api):
    client, project_id, conn = api
    response = client.post(f"/api/projects/{project_id}/labels", json={
        "field": "title", "is_correct": False, "expected_value": "Titulo real", "author": "ana"})
    assert response.status_code == 201
    conn.rollback()
    assert conn.execute("SELECT expected_value FROM labels").fetchone()["expected_value"] == "Titulo real"


def test_etiqueta_correcta_confirma_valor_extraido(api):
    client, project_id, _ = api
    response = client.post(f"/api/projects/{project_id}/labels", json={
        "field": "budget_max", "is_correct": True, "author": "ana"})
    assert response.status_code == 201 and float(response.json()["expected_value"]) == 750.0


@pytest.mark.parametrize("body", [
    {"field": "title", "is_correct": False, "author": "ana"},
    {"field": "owner_id", "is_correct": True, "author": "ana"},
    {"field": "category", "is_correct": True, "author": "ana"},
    {"field": "title", "is_correct": True, "author": ""},
])
def test_etiquetas_invalidas_rechazadas(api, body):
    client, project_id, _ = api
    assert client.post(f"/api/projects/{project_id}/labels", json=body).status_code == 422


def test_origen_externo_no_puede_etiquetar(api):
    client, project_id, _ = api
    response = client.post(f"/api/projects/{project_id}/labels", headers={"origin": "https://evil.example"},
                           json={"field": "title", "is_correct": True, "author": "ana"})
    assert response.status_code == 403


def test_proyecto_inexistente_da_404(api):
    client, _, _ = api
    assert client.get("/api/projects/999999").status_code == 404


def test_conexion_de_lectura_rechaza_escrituras(api):
    _, _, _ = api
    generator = read_conn()
    conn = next(generator)
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        conn.execute("UPDATE projects SET title='x'")
    generator.close()


def test_fuentes_y_costos(api):
    client, _, _ = api
    assert client.get("/api/sources").json()[0]["project_count"] == 1
    costs = client.get("/api/costs").json()
    assert costs["by_agent"] == [] and costs["by_run"][0]["calls"] == 0
    assert client.get("/api/filter-quality").json() == []


def test_rubrica_coincide_con_la_del_calculo():
    from scripts.rate import load_rubric
    body = TestClient(app).get("/api/rubric").json()
    rubric = load_rubric()
    assert body == {"version": rubric["version"], "weights": rubric["weights"], "penalties": rubric["penalties"]}


def test_html_se_revalida_siempre():
    from dashboard.api.main import WEB_DIST
    if not WEB_DIST.is_dir():
        pytest.skip("frontend sin compilar")
    response = TestClient(app).get("/")
    assert response.headers["cache-control"] == "no-cache"
