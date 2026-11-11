"""Tests de integracion contra Postgres; el HTTP siempre es simulado."""
import json
from pathlib import Path

import httpx
import pytest

from scripts.db import migrate
from scripts.ingest import run_ingest
from scripts.registry import SourceNotAllowed, sync_registry
from tests.conftest import api_body, make_project, mock_client


def ok(projects):
    return lambda request: httpx.Response(200, json=api_body(projects))


def count(conn, table):
    return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def test_esquema_tiene_las_13_tablas_del_prd_y_propuestas(conn):
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name <> 'schema_migrations'"
    ).fetchall()
    # 13 tablas del PRD + proposals (migracion 006, presupuestos pedidos por el titular).
    assert len(rows) == 14 and "proposals" in {r["table_name"] for r in rows}
    assert migrate(conn) == []  # idempotente


@pytest.mark.parametrize("legal_status,active", [("pendiente", True), ("prohibido", True), ("permitido", False)])
def test_fuente_no_permitida_no_toca_la_red(conn, config, legal_status, active):
    calls = []
    with pytest.raises(SourceNotAllowed):
        run_ingest(conn, "freelancer", client=mock_client(ok([]), calls), **config(legal_status, active))
    assert calls == [] and count(conn, "runs") == 0


def test_configuracion_real_bloquea_workana(conn):
    calls = []
    with pytest.raises(SourceNotAllowed):
        run_ingest(conn, "workana", client=mock_client(ok([]), calls))
    assert calls == []


def test_corrida_ok_guarda_proyecto_snapshot_y_version(conn, config):
    cfg = config()
    result = run_ingest(conn, "freelancer", client=mock_client(ok([make_project(1)])), **cfg)
    assert result["status"] == "ok" and result["items"] == 1 and result["pages"] == 1
    assert count(conn, "projects") == 1 and count(conn, "project_versions") == 1
    snapshot = conn.execute("SELECT * FROM raw_snapshots").fetchone()
    assert Path(snapshot["file_path"]).is_relative_to(cfg["snapshot_dir"])
    stored = json.loads(Path(snapshot["file_path"]).read_text(encoding="utf-8"))
    assert "owner_id" not in stored["result"]["projects"][0]
    run = conn.execute("SELECT * FROM runs").fetchone()
    assert run["finished_at"] is not None and run["search_profile_id"] is not None


def test_repetir_sin_cambios_no_duplica_ni_versiona(conn, config):
    for _ in range(2):
        run_ingest(conn, "freelancer", client=mock_client(ok([make_project(1)])), **config())
    assert count(conn, "projects") == 1 and count(conn, "project_versions") == 1


def test_cambio_de_propuestas_crea_version_sin_sobrescribir_historia(conn, config):
    run_ingest(conn, "freelancer", client=mock_client(ok([make_project(1)])), **config())
    changed = make_project(1, bid_stats={"bid_count": 9}, budget={"minimum": 250.0, "maximum": 900.0})
    run_ingest(conn, "freelancer", client=mock_client(ok([changed])), **config())
    versions = conn.execute("SELECT changed_fields FROM project_versions ORDER BY id").fetchall()
    assert len(versions) == 2
    assert versions[1]["changed_fields"]["bid_count"] == {"old": 5, "new": 9}
    assert versions[1]["changed_fields"]["budget_max"] == {"old": 750.0, "new": 900.0}
    assert set(versions[1]["changed_fields"]) == {"bid_count", "budget_max"}


def test_mas_del_10_por_ciento_incompleto_marca_cambio_de_estructura(conn, config):
    projects = [make_project(i) for i in range(1, 9)] + [make_project(9, title=None), make_project(10, title=None)]
    result = run_ingest(conn, "freelancer", client=mock_client(ok(projects)), **config())
    assert result["status"] == "cambio_estructura"
    assert count(conn, "projects") == 0  # no pasa al analisis
    assert count(conn, "raw_snapshots") == 1  # se puede re-extraer


def test_exactamente_10_por_ciento_es_parcial(conn, config):
    projects = [make_project(i) for i in range(1, 10)] + [make_project(10, title=None)]
    result = run_ingest(conn, "freelancer", client=mock_client(ok(projects)), **config())
    assert result["status"] == "parcial" and count(conn, "projects") == 9


def test_bloqueo_marca_corrida_y_no_guarda_proyectos(conn, config):
    client = mock_client(lambda r: httpx.Response(429, text="Too many"))
    result = run_ingest(conn, "freelancer", client=client, **config())
    assert result["status"] == "bloqueada" and count(conn, "projects") == 0
    assert conn.execute("SELECT status FROM runs").fetchone()["status"] == "bloqueada"


def test_error_a_mitad_conserva_lo_obtenido_como_parcial(conn, config):
    responses = iter([httpx.Response(200, json=api_body([make_project(1)])), httpx.Response(500, json={"status": "error"})])
    result = run_ingest(conn, "freelancer", client=mock_client(lambda r: next(responses)),
                        **config(keywords=("seo", "ux")))
    assert result["status"] == "parcial" and result["items"] == 1 and result["errors"]


def test_mismo_proyecto_en_dos_busquedas_se_deduplica(conn, config):
    result = run_ingest(conn, "freelancer", client=mock_client(ok([make_project(1)])),
                        **config(keywords=("seo", "ux")))
    assert result["pages"] == 2 and result["items"] == 1 and count(conn, "projects") == 1


def test_casi_duplicado_entre_fuentes_se_marca(conn, config):
    run_ingest(conn, "freelancer", client=mock_client(ok([make_project(1)])), **config())
    original = conn.execute("SELECT id, source_id FROM projects").fetchone()
    conn.execute(
        """INSERT INTO sources (name, base_url, access_mode, legal_status, rate_limit_per_min, active)
           VALUES ('otra','https://o.test','api','permitido',1,TRUE)""")
    conn.execute("UPDATE projects SET source_id=(SELECT id FROM sources WHERE name='otra')")
    conn.commit()
    run_ingest(conn, "freelancer", client=mock_client(ok([make_project(2, title="Proyecto SEO 1", description="Descripcion unica numero 1 del trabajo")])), **config())
    new = conn.execute("SELECT near_duplicate_of FROM projects WHERE external_id='2'").fetchone()
    assert new["near_duplicate_of"] == original["id"]


def test_cambiar_criterios_crea_version_y_la_corrida_la_registra(conn, config):
    run_ingest(conn, "freelancer", client=mock_client(ok([])), **config(keywords=("seo",)))
    run_ingest(conn, "freelancer", client=mock_client(ok([])), **config(keywords=("seo", "ux")))
    rows = conn.execute("SELECT version, active FROM search_profiles ORDER BY version").fetchall()
    assert [(r["version"], r["active"]) for r in rows] == [(1, False), (2, True)]
    used = conn.execute(
        "SELECT p.version FROM runs r JOIN search_profiles p ON p.id=r.search_profile_id ORDER BY r.id"
    ).fetchall()
    assert [r["version"] for r in used] == [1, 2]


def test_sincronizar_sin_cambios_no_crea_version(conn, config):
    cfg = config()
    for _ in range(2):
        sync_registry(conn, cfg["sources_path"], cfg["profiles_path"])
    assert count(conn, "search_profiles") == 1
