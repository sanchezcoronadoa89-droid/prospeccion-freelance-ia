"""Filtros por moneda, idioma, pais y region en la API del dashboard."""
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from dashboard.api.main import app
from scripts import ingest
from tests.conftest import api_body, make_project, mock_client


@pytest.fixture
def api(conn, config, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    projects = [
        make_project(1, currency={"code": "INR", "exchange_rate": 0.012, "country": "IN"},
                     budget={"minimum": 10000.0, "maximum": 20000.0}),
        make_project(2, currency={"code": "USD", "exchange_rate": 1.0, "country": "US"}),
        make_project(3, currency={"code": "USD", "exchange_rate": 1.0, "country": "US"}),
        make_project(4, currency={"code": "XYZ", "exchange_rate": 1.0, "country": "ZZ"}),
    ]
    client = mock_client(lambda r: httpx.Response(200, json=api_body(projects)))
    ingest.run_ingest(conn, "freelancer", client=client, **config())
    # El proyecto 3 esta en espanol (el perfil de prueba solo admite ingles al ingerir)
    # y menciona que el cliente esta en Mexico.
    conn.execute("UPDATE projects SET language = 'es' WHERE external_id = '3'")
    conn.execute(
        """INSERT INTO classifications (project_id, category, relevance, client_country, justification)
           SELECT id, 'marketing', 0.9, 'MX', 'x' FROM projects WHERE external_id = '3'""")
    conn.commit()
    return TestClient(app)


def ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return sorted(item["external_id"] for item in response.json()["items"])


def test_filtros_de_moneda_e_idioma(api):
    assert ids(api.get("/api/projects", params={"currency": "usd"})) == ["2", "3"]
    assert ids(api.get("/api/projects", params={"language": "es"})) == ["3"]


def test_pais_mencionado_tiene_prioridad_sobre_la_moneda(api):
    assert ids(api.get("/api/projects", params={"country": "US"})) == ["2"]
    assert ids(api.get("/api/projects", params={"country": "mx"})) == ["3"]
    item = next(i for i in api.get("/api/projects").json()["items"] if i["external_id"] == "3")
    assert item["market_country"] == "MX" and item["market_region"] == "Latinoamérica"
    assert item["market_approximate"] is False
    approx = next(i for i in api.get("/api/projects").json()["items"] if i["external_id"] == "1")
    assert approx["market_country"] == "IN" and approx["market_approximate"] is True


def test_filtro_por_region(api):
    assert ids(api.get("/api/projects", params={"region": "Asia"})) == ["1"]
    assert ids(api.get("/api/projects", params={"region": "Latinoamérica"})) == ["3"]
    assert ids(api.get("/api/projects", params={"region": "Otra"})) == ["4"]
    assert api.get("/api/projects", params={"region": "Marte"}).status_code == 422
    assert api.get("/api/projects", params={"country": "Mexico"}).status_code == 422


def test_facetas(api):
    body = api.get("/api/facets").json()
    assert {"value": "USD", "n": 2} in body["currencies"]
    assert {r["value"] for r in body["regions"]} == {"Asia", "Norteamérica", "Latinoamérica", "Otra"}
    mexico = next(c for c in body["countries"] if c["value"] == "MX")
    assert mexico["mentioned"] == 1 and mexico["region"] == "Latinoamérica"


def test_corridas_incluyen_cobertura(api):
    run = api.get("/api/runs").json()[0]
    assert run["mode"] == "completa" and "coverage" in run
