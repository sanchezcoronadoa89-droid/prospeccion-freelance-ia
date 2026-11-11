"""Fixtures. Los tests nunca usan la red: todo HTTP pasa por httpx.MockTransport."""
import os
from datetime import datetime, timezone

import httpx
import psycopg
import pytest
import yaml
from dotenv import load_dotenv
from psycopg.rows import dict_row

from scripts.db import ROOT, migrate

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)
ROBOTS = "User-agent: *\nDisallow: /private/\n"


def make_project(pid=1, **overrides) -> dict:
    """Proyecto sintetico con la forma de la API; no contiene datos reales."""
    base = {
        "id": pid, "owner_id": 999, "title": f"Proyecto SEO {pid}", "status": "active",
        "seo_url": f"seo/proyecto-{pid}", "description": f"Descripcion unica numero {pid} del trabajo",
        "preview_description": "Vista previa",
        "currency": {"code": "USD", "exchange_rate": 1.0},
        "jobs": [{"name": "SEO"}], "submitdate": int(NOW.timestamp()) - 3600, "type": "fixed",
        "budget": {"minimum": 250.0, "maximum": 750.0},
        "bid_stats": {"bid_count": 5}, "language": "en", "deleted": False, "nonpublic": False,
    }
    base.update(overrides)
    return base


def api_body(projects) -> dict:
    return {"status": "success", "result": {"projects": projects}}


def mock_client(api_handler, calls=None) -> httpx.Client:
    """Cliente simulado: robots.txt fijo y la API respondida por api_handler."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        return api_handler(request)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def conn():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Falta TEST_DATABASE_URL")
    try:
        connection = psycopg.connect(url, row_factory=dict_row, connect_timeout=5)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres de pruebas no disponible: {exc}")
    connection.execute("DROP SCHEMA public CASCADE")
    connection.execute("CREATE SCHEMA public")
    connection.commit()
    migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def config(tmp_path):
    """Config de prueba con una fuente 'permitido', ajena a config/sources.yaml."""

    def build(legal_status="permitido", active=True, keywords=("seo",), page_size=50, max_pages=2):
        sources = tmp_path / "sources.yaml"
        profiles = tmp_path / "profiles.yaml"
        sources.write_text(yaml.safe_dump({"sources": [{
            "name": "freelancer", "base_url": "https://api.test", "access_mode": "api",
            "legal_status": legal_status, "rate_limit_per_min": 60, "active": active,
        }]}), encoding="utf-8")
        profiles.write_text(yaml.safe_dump({"profiles": {"freelancer": {
            "include_keywords": list(keywords), "exclude_keywords": ["data entry"],
            "languages": ["en"], "min_budget_usd": 100, "max_age_days": 14,
            "max_pages": max_pages, "page_size": page_size,
        }}}), encoding="utf-8")
        return {"sources_path": sources, "profiles_path": profiles,
                "snapshot_dir": tmp_path / "snap", "now": NOW, "sleep": lambda _: None}

    return build
