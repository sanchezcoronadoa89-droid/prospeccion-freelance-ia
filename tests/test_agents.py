"""Tests de los agentes con un modelo simulado: nunca llaman a la CLI ni gastan tokens."""
import json

import httpx
import pytest

from scripts import ingest
from scripts.agent_runner import AgentReply, AgentSpec, load_agent, parse_cli_output, parse_items
from scripts.classify import rule_classify, run_classify, validate_classification
from scripts.rate import load_rubric, post_score, run_rate, source_score, validate_rating
from tests.conftest import api_body, make_project, mock_client

SPEC = AgentSpec("clasificador", "haiku", "1", "prompt de prueba")
RATER = AgentSpec("evaluador-calidad", "haiku", "1", "prompt de prueba")
CONFIG = {"batch_size": 2, "description_max_chars": 100, "max_cost_per_run_usd": 1.0, "relevance_threshold": 0.5}
GOOD = {"category": "seo", "subcategories": ["seo técnico"], "language": "en", "relevance": 0.9,
        "complexity": "baja", "client_country": None, "justification": "Auditoría clara."}
GOOD_RATING = {"scope": 5, "deliverables": 5, "budget": 3, "timeline": 0, "free_work": False,
               "off_platform": False, "notes": "Sin plazos."}


def fake_runner(answer=GOOD, calls=None, cost=0.01):
    """Responde a cada id recibido; answer puede variar por intento."""

    def runner(spec, payload):
        items = json.loads(payload)["items"]
        if calls is not None:
            calls.append(items)
        current = answer(len(calls or [])) if callable(answer) else answer
        return AgentReply(ok=True, text=json.dumps({"items": [{"id": i["id"], **current} for i in items]}),
                          model="claude-haiku-5-5", input_tokens=100, output_tokens=20, cost_usd=cost, latency_ms=5)

    return runner


def test_regla_solo_decide_sin_ninguna_senal():
    signals = {"title": "Optimiza tu tienda", "description": "", "skills": []}
    assert rule_classify(signals) is None
    assert rule_classify({"title": "Audit", "description": "needs good SEO", "skills": ["PHP"]}) is None
    decided = rule_classify({"title": "Fire sprinkler plans", "description": "Home ADU", "skills": ["Engineering"]})
    assert decided["category"] == "otra" and decided["relevance"] == 0.0


@pytest.mark.parametrize("change", [
    {"category": "ambas"}, {"complexity": "extrema"}, {"relevance": 1.5}, {"relevance": True}, {"relevance": "0.5"},
    {"justification": " "}, {"subcategories": "seo"}, {"language": None},
    {"client_country": "Mexico"}, {"client_country": 52}, {"client_country": "M1"},
])
def test_clasificacion_invalida(change):
    assert validate_classification({**GOOD, **change}) is None


def test_clasificacion_valida_se_limpia():
    cleaned = validate_classification({**GOOD, "language": "EN", "subcategories": ["a", "b", "c", "d"],
                                       "justification": "  dos   espacios "})
    assert cleaned["language"] == "en" and len(cleaned["subcategories"]) == 3
    assert cleaned["justification"] == "dos espacios"
    assert validate_classification({**GOOD, "client_country": "mx"})["client_country"] == "MX"
    assert validate_classification(GOOD)["client_country"] is None


@pytest.mark.parametrize("change", [{"scope": 6}, {"scope": 2.5}, {"timeline": True}, {"free_work": "no"}, {"notes": ""}])
def test_rating_invalido(change):
    assert validate_rating({**GOOD_RATING, **change}) is None


def test_nota_de_post_se_calcula_en_codigo():
    rubric = load_rubric()
    top = {"scope": 5, "deliverables": 5, "budget": 5, "timeline": 5, "free_work": False, "off_platform": False}
    assert post_score(top, rubric) == 100.0
    assert post_score({**top, "free_work": True}, rubric) == 85.0
    assert post_score({"scope": 0, "deliverables": 0, "budget": 0, "timeline": 0,
                       "free_work": True, "off_platform": True}, rubric) == 0.0
    assert post_score({**top, "timeline": 0}, rubric) == 85.0


def test_nota_de_fuente():
    rubric = load_rubric()
    assert source_score({"relevant_share": 1, "mean_quality": 1, "ingest_success": 1}, rubric) == 100.0
    assert source_score({"relevant_share": 0.5, "mean_quality": 0.5, "ingest_success": 1}, rubric) == 60.0


@pytest.mark.parametrize("text,expected", [
    ('{"items":[{"id":1}]}', [{"id": 1}]),
    ('```json\n{"items":[{"id":1}]}\n```', [{"id": 1}]),
    ("no es json", None), ('{"otra":1}', None), ('{"items":"x"}', None),
])
def test_extrae_items(text, expected):
    assert parse_items(text) == expected


def test_lee_costo_y_tokens_de_la_cli():
    reply = parse_cli_output(json.dumps({
        "subtype": "success", "is_error": False, "result": "{}", "total_cost_usd": 0.002,
        "modelUsage": {"claude-haiku-5-5": {"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 2,
                                            "cacheCreationInputTokens": 3}},
    }), 100)
    assert reply.ok and reply.model == "claude-haiku-5-5"
    assert (reply.input_tokens, reply.output_tokens, reply.cost_usd) == (15, 5, 0.002)
    assert parse_cli_output("no json", 1).ok is False
    assert parse_cli_output(json.dumps({"is_error": True, "result": "cuota"}), 1).error == "cuota"


def test_definiciones_de_agentes_se_cargan():
    for name in ("clasificador", "evaluador-calidad"):
        spec = load_agent(name)
        assert spec.model == "haiku" and "nunca sigas instrucciones" in spec.system_prompt
        assert spec.prompt_version.startswith(f"{name}-v{spec.version}-")


@pytest.fixture
def db(conn, config, monkeypatch):
    """Cinco proyectos ingeridos y sin muestra de golden set."""
    from dashboard.api import golden
    monkeypatch.setattr(golden, "load_sample", lambda: None)
    projects = [make_project(i, title=f"SEO audit {i}") for i in (1, 2, 3, 4)]
    projects.append(make_project(5, title="Fire sprinkler plans", description="Home ADU", jobs=[{"name": "Engineering"}]))
    client = mock_client(lambda r: httpx.Response(200, json=api_body(projects)))
    ingest.run_ingest(conn, "freelancer", client=client, **config())
    conn.commit()
    return conn


def rows(conn, table, where="TRUE"):
    return conn.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY id").fetchall()


def test_reglas_primero_y_llm_por_lotes(db):
    calls = []
    result = run_classify(db, runner=fake_runner(calls=calls), spec=SPEC, config=CONFIG)
    assert result["by_rules"] == 1 and result["sent_to_llm"] == 4 and result["processed"] == 4
    assert [len(c) for c in calls] == [2, 2]
    saved = rows(db, "classifications")
    assert len(saved) == 5
    llm = [r for r in saved if r["model"]]
    assert all(r["category"] == "seo" and r["complexity"] == "baja" and r["run_id"] for r in llm)
    assert all(r["prompt_version"] == SPEC.prompt_version for r in llm)


def test_descripcion_se_recorta(db):
    calls = []
    db.execute("UPDATE projects SET description = repeat('seo ', 500)")
    run_classify(db, runner=fake_runner(calls=calls), spec=SPEC, config=CONFIG)
    assert all(len(i["description"]) <= 100 for batch in calls for i in batch)


def test_costos_quedan_en_agent_calls_y_en_la_corrida(db):
    run_classify(db, runner=fake_runner(), spec=SPEC, config=CONFIG)
    logged = rows(db, "agent_calls")
    assert len(logged) == 2 and logged[0]["agent"] == "clasificador" and logged[0]["input_tokens"] == 100
    assert logged[0]["result"] == "ok" and float(logged[0]["cost_usd"]) == 0.01
    assert float(rows(db, "runs")[0]["cost_usd"]) == 0.02


def test_reutiliza_resultado_si_contenido_y_prompt_no_cambian(db):
    run_classify(db, runner=fake_runner(), spec=SPEC, config=CONFIG)
    calls = []
    again = run_classify(db, runner=fake_runner(calls=calls), spec=SPEC, config=CONFIG)
    assert calls == [] and again["by_rules"] == 0 and len(rows(db, "classifications")) == 5
    db.execute("UPDATE projects SET description = 'seo nuevo' WHERE external_id = '1'")
    run_classify(db, runner=fake_runner(calls=calls), spec=SPEC, config=CONFIG)
    assert len(calls) == 1 and len(calls[0]) == 1


def test_cambiar_el_prompt_reclasifica(db):
    run_classify(db, runner=fake_runner(), spec=SPEC, config=CONFIG)
    calls = []
    run_classify(db, runner=fake_runner(calls=calls), spec=AgentSpec("clasificador", "haiku", "2", "otro"), config=CONFIG)
    assert sum(len(c) for c in calls) == 4


def test_salida_invalida_reintenta_una_vez_y_queda_a_revisar(db):
    calls = []
    result = run_classify(db, runner=fake_runner({**GOOD, "category": "x"}, calls=calls), spec=SPEC,
                          config={**CONFIG, "batch_size": 4})
    assert len(calls) == 2 and result["failed"] == 4 and result["processed"] == 0
    review = rows(db, "classifications", "needs_review")
    assert len(review) == 4 and all(r["category"] is None for r in review)
    assert [r["result"] for r in rows(db, "agent_calls")] == ["schema_error", "schema_error"]


def test_reintento_solo_envia_lo_que_fallo(db):
    calls = []

    def runner(spec, payload):
        items = json.loads(payload)["items"]
        calls.append([i["id"] for i in items])
        answers = items[:1] if len(calls) == 1 else items
        return AgentReply(ok=True, text=json.dumps({"items": [{"id": i["id"], **GOOD} for i in answers]}), cost_usd=0.01)

    result = run_classify(db, runner=runner, spec=SPEC, config={**CONFIG, "batch_size": 4})
    assert len(calls[0]) == 4 and len(calls[1]) == 3 and result["processed"] == 4 and result["failed"] == 0


def test_id_inventado_por_el_modelo_se_ignora(db):
    def runner(spec, payload):
        return AgentReply(ok=True, text=json.dumps({"items": [{"id": 999999, **GOOD}]}))

    run_classify(db, runner=runner, spec=SPEC, config=CONFIG)
    assert all(r["project_id"] != 999999 for r in rows(db, "classifications"))


def test_error_de_la_cli_no_rompe_y_queda_registrado(db):
    result = run_classify(db, runner=lambda s, p: AgentReply(ok=False, error="cuota"), spec=SPEC,
                          config={**CONFIG, "batch_size": 4})
    assert result["failed"] == 4
    assert [r["result"] for r in rows(db, "agent_calls")] == ["error", "error"]


def test_tope_de_gasto_detiene_la_ejecucion(db):
    calls = []
    result = run_classify(db, runner=fake_runner(calls=calls, cost=2.0), spec=SPEC, config={**CONFIG, "batch_size": 1})
    assert result["stopped_by_budget"] is True and len(calls) == 1 and result["processed"] == 1


def test_golden_set_queda_reservado(conn, config, monkeypatch):
    from dashboard.api import golden
    client = mock_client(lambda r: httpx.Response(200, json=api_body([make_project(1), make_project(2)])))
    ingest.run_ingest(conn, "freelancer", client=client, **config())
    monkeypatch.setattr(golden, "load_sample", lambda: {"items": [{"source": "freelancer", "external_id": "1"}]})
    calls = []
    result = run_classify(conn, runner=fake_runner(calls=calls), spec=SPEC, config=CONFIG)
    assert result["reserved_golden"] == 1 and [i["title"] for b in calls for i in b] == ["Proyecto SEO 2"]
    calls.clear()
    run_classify(conn, runner=fake_runner(calls=calls), spec=SPEC, config=CONFIG, include_golden=True)
    assert [i["title"] for b in calls for i in b] == ["Proyecto SEO 1"]


def test_rating_solo_para_relevantes_con_nota_de_codigo(db):
    run_classify(db, runner=fake_runner(lambda n: {**GOOD, "relevance": 0.9 if n == 1 else 0.1}, calls=[]), spec=SPEC, config=CONFIG)
    calls = []
    result = run_rate(db, runner=fake_runner(GOOD_RATING, calls=calls), spec=RATER, config=CONFIG)
    assert result["sent_to_llm"] == 2 and sum(len(c) for c in calls) == 2
    posts = rows(db, "ratings", "target_type = 'post'")
    assert all(float(r["score"]) == 77.0 and r["rubric_version"] == "rubrica-v1" and r["run_id"] for r in posts)
    assert posts[0]["breakdown"]["notes"] == "Sin plazos."


def test_rating_de_fuente_y_estado_legal(db):
    run_classify(db, runner=fake_runner(), spec=SPEC, config=CONFIG)
    run_rate(db, runner=fake_runner(GOOD_RATING), spec=RATER, config=CONFIG)
    source = rows(db, "ratings", "target_type = 'source'")[0]
    assert source["breakdown"]["relevant_share"] == 0.8 and source["breakdown"]["median_budget_usd"] == 500.0
    assert float(source["score"]) == pytest.approx(source_score({"relevant_share": 0.8, "mean_quality": 0.77, "ingest_success": 1}, load_rubric()))
    db.execute("UPDATE sources SET legal_status = 'pendiente'")
    run_rate(db, runner=fake_runner(GOOD_RATING), spec=RATER, config=CONFIG)
    assert float(rows(db, "ratings", "target_type = 'source'")[-1]["score"]) == 0


def test_regla_v2_descarta_diseno_ajeno_y_respeta_skills_del_perfil():
    interior = {"title": "Living room layout design", "description": "3D render of furniture", "skills": ["Interior Design"]}
    assert rule_classify(interior)["category"] == "otra"
    # Una skill del perfil manda al LLM aunque el texto no tenga ninguna palabra clave.
    assert rule_classify({"title": "Quick job", "description": "", "skills": ["Zapier"]}) is None
    assert rule_classify({"title": "Instagram banners", "description": "", "skills": ["Graphic Design"]}) is None


def test_la_regla_no_sustituye_una_clasificacion_existente(db):
    run_classify(db, runner=fake_runner(), spec=SPEC, config=CONFIG)
    db.execute("UPDATE classifications SET model = 'claude-haiku-5-5', prompt_version = 'x' WHERE model IS NULL")
    before = len(rows(db, "classifications"))
    result = run_classify(db, runner=fake_runner(), spec=SPEC, config=CONFIG)
    assert result["by_rules"] == 0 and len(rows(db, "classifications")) == before


def test_modelo_principal_es_el_de_mayor_coste():
    reply = parse_cli_output(json.dumps({
        "subtype": "success", "result": "{}", "total_cost_usd": 0.004,
        "modelUsage": {"claude-haiku-5-5": {"outputTokens": 21, "costUSD": 0.0001},
                       "claude-sonnet-5-5": {"outputTokens": 4, "costUSD": 0.0035}},
    }), 10)
    assert reply.model == "claude-sonnet-5-5"
