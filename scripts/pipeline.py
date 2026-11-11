"""/pipeline <fuente>: ingesta, clasificacion y rating en una sola orden.

Uso: python -m scripts.pipeline freelancer [--full]
Si la ingesta no queda en ok o parcial, no se ejecutan los agentes (RF-ING-05).
Pensado para lanzarse a mano o desde el Programador de tareas de Windows.
"""
import argparse
import json
import sys

from scripts.classify import run_classify
from scripts.db import AlreadyRunning, connect, pipeline_lock
from scripts.ingest import run_ingest
from scripts.rate import run_rate
from scripts.registry import SourceNotAllowed


def run_pipeline(conn, source: str, *, full=False, ingest=run_ingest, classify=run_classify, rate=run_rate) -> dict:
    try:
        ingested = ingest(conn, source, full=full)
    except SourceNotAllowed as exc:
        return {"status": "no_ejecutada", "motivo": str(exc)}
    summary = {"ingest": ingested}
    if ingested["status"] not in ("ok", "parcial"):
        summary["status"] = "detenida"
        summary["motivo"] = f"Ingesta en estado {ingested['status']}: no pasa a los agentes"
        return summary
    summary["classify"] = classify(conn, ingested["run_id"])
    summary["rate"] = rate(conn, ingested["run_id"])
    stopped = summary["classify"]["stopped_by_budget"] or summary["rate"]["stopped_by_budget"]
    summary["status"] = "tope_de_gasto" if stopped else "ok"
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ingesta, clasificacion y rating")
    parser.add_argument("source")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args(argv)
    with connect() as conn:
        try:
            with pipeline_lock(conn):
                summary = run_pipeline(conn, args.source, full=args.full)
        except AlreadyRunning as exc:
            print(json.dumps({"status": "ocupado", "motivo": str(exc)}, ensure_ascii=False))
            return 4
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return 0 if summary["status"] == "ok" else 3


if __name__ == "__main__":
    sys.exit(main())
