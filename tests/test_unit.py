"""Tests sin base de datos: parser, sanitizado, conector, kappa y similitud."""
import httpx
import pytest

from evals.kappa import cohen_kappa
from scripts.connectors.freelancer import BlockedError, FetchError, FreelancerConnector, sanitize_payload
from scripts.ingest import similarity
from scripts.parsers.freelancer import missing_required, parse_project, passes_criteria
from scripts.registry import SourceNotAllowed, assert_source_allowed
from tests.conftest import NOW, api_body, make_project, mock_client

CRITERIA = {"include_keywords": ["seo"], "languages": ["en"], "page_size": 2, "max_pages": 3}


def connector(api_handler, calls=None):
    return FreelancerConnector("https://api.test", 60, mock_client(api_handler, calls), sleep=lambda _: None)


def parsed(**overrides):
    return parse_project(make_project(**overrides), "https://api.test")


def test_parser_normaliza_campos():
    p = parsed()
    assert p["external_id"] == "1" and p["url"] == "https://api.test/projects/seo/proyecto-1"
    assert p["budget_min"] == 250.0 and p["currency"] == "USD" and p["skills"] == ["SEO"]
    assert p["project_type"] == "fixed" and p["bid_count"] == 5 and missing_required(p) == []


def test_parser_detecta_campo_obligatorio_faltante():
    assert "title" in missing_required(parsed(title=None))
    assert "budget_min" in missing_required(parsed(budget=None))


def test_sanitizado_elimina_datos_personales():
    clean = sanitize_payload({"status": "success", "result": {
        "users": {"999": {"username": "cliente"}},
        "projects": [make_project(description="Escribe a ana@correo.com o al +34 600 123 456")],
    }})
    project = clean["result"]["projects"][0]
    assert "users" not in clean["result"] and "owner_id" not in project
    assert "ana@correo.com" not in project["description"]
    assert "600 123 456" not in project["description"]


def test_sanitizado_no_altera_presupuestos_en_texto():
    clean = sanitize_payload(api_body([make_project(description="Presupuesto 1500 USD en 30 dias")]))
    assert clean["result"]["projects"][0]["description"] == "Presupuesto 1500 USD en 30 dias"


@pytest.mark.parametrize("overrides,expected", [
    ({}, True),
    ({"title": "Data Entry urgente"}, False),
    ({"language": "fr"}, False),
    ({"submitdate": int(NOW.timestamp()) - 20 * 86400}, False),
    ({"budget": {"minimum": 10.0, "maximum": 50.0}}, False),
    ({"nonpublic": True}, False),
])
def test_filtro_de_criterios(overrides, expected):
    criteria = {"exclude_keywords": ["data entry"], "languages": ["en"], "max_age_days": 14, "min_budget_usd": 100}
    assert passes_criteria(parsed(**overrides), criteria, NOW) is expected


def test_presupuesto_minimo_usa_tipo_de_cambio():
    project = parsed(currency={"code": "INR", "exchange_rate": 0.012}, budget={"minimum": 1000.0, "maximum": 2000.0})
    assert passes_criteria(project, {"min_budget_usd": 100}, NOW) is False


def test_conector_pagina_y_para_en_pagina_corta():
    responses = iter([[make_project(1), make_project(2)], [make_project(3)]])
    calls = []
    pages = list(connector(lambda r: httpx.Response(200, json=api_body(next(responses))), calls).fetch_pages(CRITERIA))
    assert len(pages) == 2 and len(calls) == 3  # robots.txt + 2 paginas


def test_conector_respeta_limite_de_tasa():
    waits = []
    c = FreelancerConnector("https://api.test", 10, mock_client(lambda r: httpx.Response(200, json=api_body([]))),
                            sleep=waits.append)
    list(c.fetch_pages(CRITERIA))
    assert waits == [6.0]  # una espera entre robots.txt y la unica pagina


@pytest.mark.parametrize("response", [
    httpx.Response(403, text="Forbidden"),
    httpx.Response(429, text="Too many"),
    httpx.Response(200, text="<html>Please solve this CAPTCHA</html>"),
])
def test_bloqueo_detiene_sin_reintentar(response):
    calls = []
    with pytest.raises(BlockedError):
        list(connector(lambda r: response, calls).fetch_pages(CRITERIA))
    assert len(calls) == 2  # robots.txt + un solo intento


def test_robots_que_prohibe_detiene_antes_de_la_api():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /api/\n")

    c = FreelancerConnector("https://api.test", 60, httpx.Client(transport=httpx.MockTransport(handler)),
                            sleep=lambda _: None)
    with pytest.raises(BlockedError):
        list(c.fetch_pages(CRITERIA))
    assert calls == ["/robots.txt"]


def test_error_de_servidor_es_fetch_error():
    with pytest.raises(FetchError):
        list(connector(lambda r: httpx.Response(500, json={"status": "error"})).fetch_pages(CRITERIA))


def test_kappa_valores_conocidos():
    assert cohen_kappa(list("aabb"), list("aabb")) == 1.0
    assert cohen_kappa(list("aabb"), list("abab")) == 0.0
    # 90 de 100 coinciden con mayoria de "si": kappa baja frente al 90 % bruto.
    a = ["si"] * 85 + ["si"] * 5 + ["no"] * 5 + ["no"] * 5
    b = ["si"] * 85 + ["no"] * 5 + ["si"] * 5 + ["no"] * 5
    assert round(cohen_kappa(a, b), 3) == 0.444


def test_similitud_ignora_mayusculas_y_espacios():
    assert similarity("Rediseño  WEB corporativa", "rediseño web corporativa") == 1.0
    assert similarity("Rediseño web", "Auditoría SEO técnica") < 0.9


@pytest.mark.parametrize("legal_status,active,allowed", [
    ("permitido", True, True),
    ("permitido", False, False),
    ("pendiente", True, False),
    ("prohibido", True, False),
])
def test_puerta_legal(legal_status, active, allowed):
    source = {"name": "x", "legal_status": legal_status, "active": active}
    if allowed:
        assert_source_allowed(source)
    else:
        with pytest.raises(SourceNotAllowed):
            assert_source_allowed(source)
