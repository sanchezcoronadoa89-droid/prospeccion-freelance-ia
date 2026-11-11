"""Acciones que el titular pidio lanzar desde el dashboard (11 nov 2026).

- Ingesta manual: lanza el mismo `scripts.pipeline` que la consola, protegido por su bloqueo.
  El dashboard no escribe datos de ingesta por si mismo.
- Presupuesto: genera y guarda un borrador de propuesta. Nunca envia nada.
"""
import subprocess
import sys
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from dashboard.api.deps import Reader, Writer, require_local_origin
from scripts import budget
from scripts.db import ROOT, AlreadyRunning, pipeline_lock
from scripts.ingest import CONNECTORS, coverage

router = APIRouter()
LOG_DIR = ROOT / "data" / "logs"
# Se sustituye en los tests para no lanzar procesos reales.
start_process = subprocess.Popen


def lock_is_free(conn, name: str) -> bool:
    """Comprueba el bloqueo sin quedarselo: lo toma y lo suelta en el acto."""
    got = conn.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS ok", (name,)).fetchone()["ok"]
    if got:
        conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (name,))
    conn.commit()
    return got


@router.get("/api/pipeline/status")
def pipeline_status(conn: Reader) -> dict:
    last = conn.execute(
        """SELECT r.id, r.status, r.mode, r.started_at, r.finished_at, r.items, r.query_stats, s.name AS source
           FROM runs r JOIN sources s ON s.id = r.source_id ORDER BY r.id DESC LIMIT 1"""
    ).fetchone()
    if last:
        last["coverage"] = coverage(last.pop("query_stats"))
    return {"running": not lock_is_free(conn, "pipeline"), "last_run": last}


class RunIn(BaseModel):
    source: str = "freelancer"
    full: bool = False


@router.post("/api/pipeline/run", status_code=202, dependencies=[Depends(require_local_origin)])
def pipeline_run(body: RunIn, conn: Reader) -> dict:
    source = conn.execute("SELECT name, legal_status, active FROM sources WHERE name = %s", (body.source,)).fetchone()
    if source is None or body.source not in CONNECTORS:
        raise HTTPException(422, "Esa fuente no tiene conector")
    if source["legal_status"] != "permitido" or not source["active"]:
        raise HTTPException(422, f"La fuente está en estado «{source['legal_status']}»: no se puede ingerir")
    if not lock_is_free(conn, "pipeline"):
        raise HTTPException(409, "Ya hay una ingesta en curso")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"pipeline-{datetime.now():%Y%m%d-%H%M%S}.log"
    args = [sys.executable, "-m", "scripts.pipeline", body.source] + (["--full"] if body.full else [])
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS) if sys.platform == "win32" else 0
    with open(log_path, "w", encoding="utf-8") as log:
        start_process(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                      creationflags=flags)
    return {"status": "iniciada", "full": body.full, "log": log_path.name}


@router.get("/api/budget/params")
def budget_params() -> dict:
    params = budget.load_params()
    data = {key: params[key] for key in ("version", "calibrated", "hourly_rate_usd", "commission", "hours_per_day")}
    data["tasks"] = {key: {"label": task["label"], "unit": task["unit"]} for key, task in params["tasks"].items()}
    return data


@router.get("/api/projects/{project_id}/proposal")
def latest_proposal(project_id: Annotated[int, Path(ge=1)], conn: Reader) -> dict | None:
    return conn.execute(
        "SELECT * FROM proposals WHERE project_id = %s ORDER BY id DESC LIMIT 1", (project_id,)
    ).fetchone()


@router.post("/api/projects/{project_id}/proposal", status_code=201, dependencies=[Depends(require_local_origin)])
def create_proposal(project_id: Annotated[int, Path(ge=1)], conn: Writer) -> dict:
    try:
        with pipeline_lock(conn, f"propuesta-{project_id}"):
            return budget.generate_proposal(conn, project_id)
    except AlreadyRunning as exc:
        raise HTTPException(409, "Ya se está generando un presupuesto para este proyecto") from exc
    except budget.ProposalError as exc:
        raise HTTPException(422, str(exc)) from exc
