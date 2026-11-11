"""Orquestacion del pipeline con etapas simuladas."""
from scripts.pipeline import run_pipeline
from scripts.registry import SourceNotAllowed


def stage(result, calls, name):
    def run(conn, *args, **kwargs):
        calls.append((name, args, kwargs))
        return result
    return run


def test_encadena_las_tres_etapas_con_la_misma_corrida():
    calls = []
    summary = run_pipeline(None, "freelancer", full=True,
                           ingest=stage({"status": "ok", "run_id": 7}, calls, "ingest"),
                           classify=stage({"stopped_by_budget": False}, calls, "classify"),
                           rate=stage({"stopped_by_budget": False}, calls, "rate"))
    assert summary["status"] == "ok"
    assert [c[0] for c in calls] == ["ingest", "classify", "rate"]
    assert calls[0][2] == {"full": True} and calls[1][1] == (7,) and calls[2][1] == (7,)


def test_ingesta_fallida_no_llama_a_los_agentes():
    calls = []
    summary = run_pipeline(None, "freelancer",
                           ingest=stage({"status": "cambio_estructura", "run_id": 7}, calls, "ingest"),
                           classify=stage({}, calls, "classify"), rate=stage({}, calls, "rate"))
    assert summary["status"] == "detenida" and [c[0] for c in calls] == ["ingest"]


def test_fuente_no_permitida():
    def blocked(conn, source, full=False):
        raise SourceNotAllowed("pendiente")

    assert run_pipeline(None, "workana", ingest=blocked)["status"] == "no_ejecutada"


def test_tope_de_gasto_se_informa():
    calls = []
    summary = run_pipeline(None, "freelancer", ingest=stage({"status": "parcial", "run_id": 1}, calls, "ingest"),
                           classify=stage({"stopped_by_budget": True}, calls, "classify"),
                           rate=stage({"stopped_by_budget": False}, calls, "rate"))
    assert summary["status"] == "tope_de_gasto"


def test_bloqueo_impide_dos_ejecuciones_a_la_vez(conn):
    import os

    import psycopg
    import pytest
    from psycopg.rows import dict_row

    from scripts.db import AlreadyRunning, pipeline_lock

    other = psycopg.connect(os.environ["TEST_DATABASE_URL"], row_factory=dict_row)
    try:
        with pipeline_lock(conn, "prueba-bloqueo"):
            with pytest.raises(AlreadyRunning):
                with pipeline_lock(other, "prueba-bloqueo"):
                    pass
        with pipeline_lock(other, "prueba-bloqueo"):
            pass  # liberado al salir del primero
    finally:
        other.close()
