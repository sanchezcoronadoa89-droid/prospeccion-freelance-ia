"""Ingesta por skills, incremental y con cobertura medida. El HTTP siempre es simulado."""
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest
import yaml

from scripts.connectors.freelancer import JOBS_PER_QUERY, FreelancerConnector
from scripts.ingest import coverage, run_ingest
from scripts.regions import market, region_for
from tests.conftest import ROBOTS, api_body, make_project

JOBS = [{"id": 10 + i, "name": f"Skill {i}"} for i in range(12)]


def recording_client(projects=(), total_count=None, requests=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if request.url.path.endswith("/jobs/"):
            return httpx.Response(200, json={"status": "success", "result": JOBS})
        body = api_body(list(projects))
        if total_count is not None:
            body["result"]["total_count"] = total_count
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def params(request) -> dict:
    return parse_qs(request.url.query.decode())


def api_requests(requests):
    return [r for r in requests if r.url.path.endswith("/active/")]


def test_skills_por_nombre_en_grupos_y_aviso_si_no_existen():
    requests = []
    connector = FreelancerConnector("https://api.test", 60, recording_client(requests=requests), sleep=lambda _: None)
    names = [f"Skill {i}" for i in range(10)] + ["No existe"]
    pages = list(connector.fetch_pages({"job_names": names, "include_keywords": ["seo"], "page_size": 50, "max_pages": 1}))
    calls = api_requests(requests)
    assert len(calls) == 3 and len(pages) == 3
    assert params(calls[0])["jobs[]"] == [str(10 + i) for i in range(JOBS_PER_QUERY)]
    assert params(calls[1])["jobs[]"] == ["18", "19"]
    assert params(calls[2])["query"] == ["seo"] and "jobs[]" not in params(calls[2])
    assert connector.warnings == ["Skill desconocida en la API: No existe"]
    assert [p.query for p in pages] == ["skills 1", "skills 2", "seo"]


def test_sin_skills_no_pide_la_taxonomia():
    requests = []
    connector = FreelancerConnector("https://api.test", 60, recording_client(requests=requests), sleep=lambda _: None)
    list(connector.fetch_pages({"include_keywords": ["seo"], "page_size": 50, "max_pages": 1}))
    assert not any(r.url.path.endswith("/jobs/") for r in requests)


@pytest.mark.parametrize("stats,expected", [
    ([{"total_count": 100, "fetched": 50}, {"total_count": 100, "fetched": 100}], 0.75),
    ([{"total_count": 10, "fetched": 40}], 1.0),
    ([{"total_count": None, "fetched": 5}], None),
    ([], None),
])
def test_cobertura(stats, expected):
    assert coverage(stats) == expected


def test_region_y_mercado():
    assert region_for("MX") == "Latinoamérica" and region_for("in") == "Asia"
    assert region_for("ZZ") == "Otra" and region_for(None) is None
    assert market("ES", "IN") == {"country": "ES", "region": "Europa", "approximate": False}
    assert market(None, "IN") == {"country": "IN", "region": "Asia", "approximate": True}
    assert market(None, None) == {"country": None, "region": None, "approximate": False}


def test_primera_corrida_completa_y_la_siguiente_incremental(conn, config):
    cfg = config()
    requests = []
    first = run_ingest(conn, "freelancer", client=recording_client([make_project(1)], 1, requests), **cfg)
    assert "from_time" not in params(api_requests(requests)[0])
    requests.clear()
    run_ingest(conn, "freelancer", client=recording_client([make_project(1)], 1, requests), **cfg)
    since = params(api_requests(requests)[0])["from_time"][0]
    runs = conn.execute("SELECT mode, since, started_at FROM runs ORDER BY id").fetchall()
    assert [r["mode"] for r in runs] == ["completa", "incremental"]
    assert runs[1]["since"] == runs[0]["started_at"] - timedelta(hours=2)
    assert int(since) == int(runs[1]["since"].timestamp())
    assert first["coverage"] == 1.0


def test_full_fuerza_corrida_completa(conn, config):
    cfg = config()
    run_ingest(conn, "freelancer", client=recording_client([make_project(1)]), **cfg)
    requests = []
    run_ingest(conn, "freelancer", client=recording_client([make_project(1)], requests=requests), full=True, **cfg)
    assert "from_time" not in params(api_requests(requests)[0])


def test_cambiar_el_perfil_vuelve_a_corrida_completa(conn, config):
    run_ingest(conn, "freelancer", client=recording_client([make_project(1)]), **config(keywords=("seo",)))
    requests = []
    run_ingest(conn, "freelancer", client=recording_client([make_project(1)], requests=requests), **config(keywords=("ux",)))
    assert "from_time" not in params(api_requests(requests)[0])


def test_cobertura_por_busqueda_queda_en_la_corrida(conn, config):
    result = run_ingest(conn, "freelancer", client=recording_client([make_project(1), make_project(2)], 8), **config())
    stats = conn.execute("SELECT query_stats FROM runs").fetchone()["query_stats"]
    assert stats == [{"query": "seo", "total_count": 8, "fetched": 2}]
    assert result["coverage"] == 0.25


def test_skill_desconocida_deja_la_corrida_parcial(conn, config, tmp_path):
    cfg = config()
    profiles = yaml.safe_load(cfg["profiles_path"].read_text(encoding="utf-8"))
    profiles["profiles"]["freelancer"]["job_names"] = ["Skill 1", "No existe"]
    cfg["profiles_path"].write_text(yaml.safe_dump(profiles), encoding="utf-8")
    result = run_ingest(conn, "freelancer", client=recording_client([make_project(1)]), **cfg)
    assert result["status"] == "parcial" and result["errors"] == ["Skill desconocida en la API: No existe"]


def test_guarda_idioma_y_pais_de_la_moneda(conn, config):
    project = make_project(1, currency={"code": "INR", "exchange_rate": 0.012, "country": "IN"},
                           budget={"minimum": 10000.0, "maximum": 20000.0})
    run_ingest(conn, "freelancer", client=recording_client([project]), **config())
    row = conn.execute("SELECT language, currency_country FROM projects").fetchone()
    assert row == {"language": "en", "currency_country": "IN"}


def test_noruega_es_europa():
    assert region_for("NO") == "Europa"


def test_codigos_de_moneda_de_la_api_en_europa():
    assert region_for("EU") == "Europa" and region_for("UK") == "Europa"
