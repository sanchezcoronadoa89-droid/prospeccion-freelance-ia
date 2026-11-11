"""Ingesta sin LLM: /ingest <fuente>.

Uso: python -m scripts.ingest freelancer [--full] [--backfill]

Por defecto es incremental: solo pide lo publicado desde la ultima corrida valida con el
mismo perfil (menos un margen). --full vuelve a pedir todo y refresca propuestas y estados
de proyectos antiguos (RF-ING-07).
"""
import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path

import httpx
from psycopg.types.json import Jsonb

from scripts.connectors.freelancer import BlockedError, FetchError, FreelancerConnector
from scripts.db import ROOT, AlreadyRunning, connect, pipeline_lock
from scripts.parsers import freelancer as freelancer_parser
from scripts.registry import (PROFILES_PATH, SOURCES_PATH, SourceNotAllowed, assert_source_allowed,
                              get_active_profile, get_source, sync_registry)

SNAPSHOT_DIR = ROOT / "data" / "snapshots"
STRUCTURE_THRESHOLD = 0.10
NEAR_DUPLICATE_THRESHOLD = 0.90
INCREMENTAL_OVERLAP = timedelta(hours=2)
TRACKED_FIELDS = ("budget_min", "budget_max", "bid_count", "status")
CONNECTORS = {"freelancer": (FreelancerConnector, freelancer_parser)}


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, " ".join(a.lower().split()), " ".join(b.lower().split())).ratio()


def _same(old, new) -> bool:
    if isinstance(old, Decimal) and new is not None:
        return old == Decimal(str(new))
    return old == new


def _jsonable(value):
    return float(value) if isinstance(value, Decimal) else value


def _finish(conn, run_id, status, pages, items, errors, query_stats) -> dict:
    stats = list(query_stats.values())
    conn.execute(
        """UPDATE runs SET finished_at=now(), status=%s, pages=%s, items=%s,
           error_count=%s, errors=%s, query_stats=%s WHERE id=%s""",
        (status, pages, items, len(errors), Jsonb(errors), Jsonb(stats), run_id),
    )
    conn.commit()
    return {"run_id": run_id, "status": status, "pages": pages, "items": items, "errors": errors,
            "coverage": coverage(stats)}


def coverage(query_stats: list[dict]) -> float | None:
    """Parte de lo que la fuente dice tener que realmente se descargo (recall de captura)."""
    expected = sum(q["total_count"] for q in query_stats if q.get("total_count"))
    fetched = sum(min(q["fetched"], q["total_count"]) for q in query_stats if q.get("total_count"))
    return round(fetched / expected, 3) if expected else None


def _save_snapshot(conn, run_id, page, number, snapshot_dir) -> int:
    body = json.dumps(page.payload, ensure_ascii=False, sort_keys=True)
    folder = Path(snapshot_dir) / f"run_{run_id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"page_{number:04d}.json"
    path.write_text(body, encoding="utf-8")
    row = conn.execute(
        "INSERT INTO raw_snapshots (run_id, url, content_hash, file_path) VALUES (%s,%s,%s,%s) RETURNING id",
        (run_id, page.url, hashlib.sha256(body.encode("utf-8")).hexdigest(), str(path)),
    ).fetchone()
    conn.commit()
    return row["id"]


def _find_near_duplicate(conn, source_id, project):
    text = f"{project['title']} {project['description'] or ''}"
    rows = conn.execute(
        """SELECT id, title, description FROM projects WHERE source_id <> %s
           AND first_seen_at > now() - interval '30 days'""",
        (source_id,),
    ).fetchall()
    for row in rows:
        if similarity(text, f"{row['title']} {row['description'] or ''}") >= NEAR_DUPLICATE_THRESHOLD:
            return row["id"]
    return None


def _upsert(conn, source_id, project, snapshot_id) -> None:
    current = conn.execute(
        f"SELECT id, {', '.join(TRACKED_FIELDS)} FROM projects WHERE source_id=%s AND external_id=%s",
        (source_id, project["external_id"]),
    ).fetchone()
    values = (project["url"], project["title"], project["description"], Jsonb(project["skills"]),
              project["budget_min"], project["budget_max"], project["currency"], project["usd_rate"],
              project["project_type"], project["posted_at"], project["bid_count"], project["status"],
              project["language"], project["currency_country"])
    if current is None:
        near = _find_near_duplicate(conn, source_id, project)
        row = conn.execute(
            """INSERT INTO projects (url, title, description, skills, budget_min, budget_max, currency,
                   usd_rate, project_type, posted_at, bid_count, status, language, currency_country,
                   source_id, external_id, near_duplicate_of)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            values + (source_id, project["external_id"], near),
        ).fetchone()
        changes = {f: {"old": None, "new": project[f]} for f in TRACKED_FIELDS}
        project_id = row["id"]
    else:
        project_id = current["id"]
        changes = {f: {"old": _jsonable(current[f]), "new": project[f]}
                   for f in TRACKED_FIELDS if not _same(current[f], project[f])}
        conn.execute(
            """UPDATE projects SET url=%s, title=%s, description=%s, skills=%s, budget_min=%s,
                   budget_max=%s, currency=%s, usd_rate=%s, project_type=%s, posted_at=%s,
                   bid_count=%s, status=%s, language=%s, currency_country=%s, last_seen_at=now()
               WHERE id=%s""",
            values + (project_id,),
        )
    if changes:
        conn.execute(
            "INSERT INTO project_versions (project_id, snapshot_id, changed_fields) VALUES (%s,%s,%s)",
            (project_id, snapshot_id, Jsonb(changes)),
        )


def incremental_since(conn, source_id: int, profile_id: int) -> datetime | None:
    """Inicio de la ultima corrida valida con este mismo perfil; si el perfil cambio, toca completa."""
    row = conn.execute(
        """SELECT max(started_at) AS started FROM runs
           WHERE source_id = %s AND search_profile_id = %s AND status IN ('ok','parcial')""",
        (source_id, profile_id),
    ).fetchone()
    return row["started"] - INCREMENTAL_OVERLAP if row["started"] else None


def run_ingest(conn, source_name, *, client=None, sources_path=SOURCES_PATH, profiles_path=PROFILES_PATH,
               snapshot_dir=SNAPSHOT_DIR, now=None, sleep=None, full=False) -> dict:
    sync_registry(conn, sources_path, profiles_path)
    source = get_source(conn, source_name)
    assert_source_allowed(source)  # Antes de cualquier acceso de red (RF-FUE-03).
    if source_name not in CONNECTORS:
        raise SourceNotAllowed(f"{source_name}: no hay conector implementado")
    connector_class, parser = CONNECTORS[source_name]
    profile = get_active_profile(conn, source["id"])
    criteria = profile["criteria"]
    now = now or datetime.now(timezone.utc)
    since = None if full else incremental_since(conn, source["id"], profile["id"])

    run_id = conn.execute(
        """INSERT INTO runs (source_id, search_profile_id, status, mode, since)
           VALUES (%s,%s,'en_curso',%s,%s) RETURNING id""",
        (source["id"], profile["id"], "incremental" if since else "completa", since),
    ).fetchone()["id"]
    conn.commit()

    owns_client = client is None
    client = client or httpx.Client(timeout=30)
    options = {"sleep": sleep} if sleep else {}
    connector = connector_class(source["base_url"], source["rate_limit_per_min"], client, **options)
    pages, errors, parsed = 0, [], []
    query_stats = defaultdict(lambda: {"query": "", "total_count": None, "fetched": 0})
    try:
        for page in connector.fetch_pages(criteria, since=since):
            pages += 1
            stats = query_stats[page.query]
            stats["query"] = page.query
            if stats["total_count"] is None:
                stats["total_count"] = page.total_count
            stats["fetched"] += len(page.payload["result"]["projects"])
            snapshot_id = _save_snapshot(conn, run_id, page, pages, snapshot_dir)
            for raw in page.payload["result"]["projects"]:
                parsed.append((parser.parse_project(raw, source["base_url"]), snapshot_id))
    except BlockedError as exc:
        return _finish(conn, run_id, "bloqueada", pages, len(parsed), [str(exc)], query_stats)
    except FetchError as exc:
        errors.append(str(exc))
    finally:
        if owns_client:
            client.close()
    errors += getattr(connector, "warnings", [])

    incomplete = [(p, parser.missing_required(p)) for p, _ in parsed if parser.missing_required(p)]
    if parsed and len(incomplete) / len(parsed) > STRUCTURE_THRESHOLD:
        message = f"{len(incomplete)} de {len(parsed)} items sin campo obligatorio"
        return _finish(conn, run_id, "cambio_estructura", pages, len(parsed), errors + [message], query_stats)

    errors += [f"Proyecto {p['external_id']} sin {fields}" for p, fields in incomplete]
    unique = {}
    for project, snapshot_id in parsed:
        if not parser.missing_required(project) and parser.passes_criteria(project, criteria, now):
            unique[project["external_id"]] = (project, snapshot_id)
    for project, snapshot_id in unique.values():
        _upsert(conn, source["id"], project, snapshot_id)
    conn.commit()
    return _finish(conn, run_id, "parcial" if errors else "ok", pages, len(unique), errors, query_stats)


def backfill_market(conn) -> int:
    """Rellena idioma y pais de la moneda en proyectos anteriores, leyendo sus snapshots."""
    found = {}
    for row in conn.execute("SELECT file_path FROM raw_snapshots ORDER BY id").fetchall():
        path = Path(row["file_path"])
        if not path.is_file():
            continue
        for item in json.loads(path.read_text(encoding="utf-8"))["result"]["projects"]:
            found[str(item.get("id"))] = (item.get("language"), (item.get("currency") or {}).get("country"))
    updated = 0
    for project in conn.execute("SELECT id, external_id FROM projects WHERE language IS NULL OR currency_country IS NULL"):
        if project["external_id"] in found:
            language, country = found[project["external_id"]]
            conn.execute("UPDATE projects SET language=%s, currency_country=%s WHERE id=%s",
                         (language, country, project["id"]))
            updated += 1
    conn.commit()
    return updated


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ingesta de una fuente registrada")
    parser.add_argument("source")
    parser.add_argument("--full", action="store_true", help="Pide todo, no solo lo nuevo")
    parser.add_argument("--backfill", action="store_true", help="Solo rellena idioma y pais de la moneda")
    args = parser.parse_args(argv)
    with connect() as conn:
        if args.backfill:
            print(json.dumps({"backfilled": backfill_market(conn)}))
            return 0
        try:
            with pipeline_lock(conn):
                result = run_ingest(conn, args.source, full=args.full)
        except AlreadyRunning as exc:
            print(json.dumps({"status": "ocupado", "motivo": str(exc)}, ensure_ascii=False))
            return 4
        except SourceNotAllowed as exc:
            print(json.dumps({"status": "no_ejecutada", "motivo": str(exc)}, ensure_ascii=False))
            return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 3


if __name__ == "__main__":
    sys.exit(main())
