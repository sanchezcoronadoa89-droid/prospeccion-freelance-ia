"""API del dashboard de validacion. Escribe etiquetas (RF-DSH-03) y, por peticion del titular,
lanza la ingesta y genera presupuestos (dashboard/api/actions.py).

Uso: python -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8000
"""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from dashboard.api.deps import LOCAL_HOSTS, Reader, Writer, read_conn, require_local_origin  # noqa: F401
from dashboard.api.actions import router as actions_router
from dashboard.api.golden import router as golden_router
from scripts import ingest
from scripts.db import ROOT
from scripts.ingest import coverage
from scripts.rate import load_rubric
from scripts.regions import OTHER as OTHER_REGION
from scripts.regions import countries_in, market, region_for, regions

AUDIT_FIELDS = ("title", "description", "budget_min", "budget_max", "currency", "project_type",
                "posted_at", "bid_count", "status", "skills", "url")
JUDGMENT_FIELDS = ("category", "relevance", "quality")
WEB_DIST = ROOT / "dashboard" / "web" / "dist"

app = FastAPI(title="Dashboard de validacion")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[*LOCAL_HOSTS, "testserver"])


@app.middleware("http")
async def revalidate_html(request: Request, call_next):
    """Que el navegador no reutilice un index.html viejo tras recompilar el frontend."""
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(psycopg.OperationalError)
def database_unavailable(_: Request, exc: psycopg.OperationalError) -> JSONResponse:
    return JSONResponse({"detail": "Base de datos no disponible"}, status_code=503)


app.include_router(golden_router)
app.include_router(actions_router)


class LabelIn(BaseModel):
    field: str
    is_correct: bool
    expected_value: Any = None
    author: str = Field(min_length=1, max_length=80)


def _project_row(conn, project_id: int) -> dict:
    rows, _ = _query_projects(conn, ["p.id = %(id)s"], {"id": project_id, "limit": 1, "offset": 0})
    if not rows:
        raise HTTPException(404, "Proyecto no encontrado")
    return rows[0]


def _query_projects(conn, where: list[str], params: dict) -> tuple[list[dict], int]:
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        f"""SELECT p.*, s.name AS source, count(*) OVER () AS total,
                   COALESCE(p.budget_max, p.budget_min) * p.usd_rate AS budget_usd,
                   c.category, c.relevance, c.complexity, c.client_country, c.justification, c.needs_review,
                   c.model AS class_model,
                   c.prompt_version, c.run_id AS class_run_id,
                   r.score AS rating, r.breakdown AS rating_breakdown, r.rubric_version, r.run_id AS rating_run_id,
                   v.run_id AS source_run_id, v.profile_version
            FROM projects p
            JOIN sources s ON s.id = p.source_id
            LEFT JOIN LATERAL (SELECT * FROM classifications x WHERE x.project_id = p.id
                               ORDER BY x.id DESC LIMIT 1) c ON TRUE
            LEFT JOIN LATERAL (SELECT * FROM ratings x WHERE x.target_type = 'post' AND x.target_id = p.id
                               ORDER BY x.id DESC LIMIT 1) r ON TRUE
            LEFT JOIN LATERAL (SELECT sn.run_id, sp.version AS profile_version
                               FROM project_versions pv
                               JOIN raw_snapshots sn ON sn.id = pv.snapshot_id
                               JOIN runs ru ON ru.id = sn.run_id
                               JOIN search_profiles sp ON sp.id = ru.search_profile_id
                               WHERE pv.project_id = p.id ORDER BY pv.id DESC LIMIT 1) v ON TRUE
            {clause}
            ORDER BY p.posted_at DESC NULLS LAST, p.id DESC
            LIMIT %(limit)s OFFSET %(offset)s""",
        params,
    ).fetchall()
    total = rows[0]["total"] if rows else 0
    for row in rows:
        row.pop("total")
        place = market(row["client_country"], row["currency_country"])
        row.update(market_country=place["country"], market_region=place["region"],
                   market_approximate=place["approximate"])
    return rows, total


# Pais del mercado: el mencionado en la publicacion o, si no hay, el de la moneda.
MARKET_COUNTRY_SQL = "COALESCE(c.client_country, p.currency_country)"


def _region_filter(region: str, params: dict) -> str:
    if region == OTHER_REGION:
        params["known_codes"] = [code for codes in regions().values() for code in codes]
        return f"{MARKET_COUNTRY_SQL} IS NOT NULL AND NOT ({MARKET_COUNTRY_SQL} = ANY(%(known_codes)s))"
    params["region_codes"] = countries_in(region)
    return f"{MARKET_COUNTRY_SQL} = ANY(%(region_codes)s)"


@app.get("/api/health")
def health(conn: Reader) -> dict:
    conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/api/runs")
def runs(conn: Reader, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[dict]:
    rows = conn.execute(
        """SELECT r.*, s.name AS source, sp.version AS profile_version,
                  EXTRACT(EPOCH FROM r.finished_at - r.started_at) AS duration_seconds
           FROM runs r JOIN sources s ON s.id = r.source_id
           JOIN search_profiles sp ON sp.id = r.search_profile_id
           ORDER BY r.id DESC LIMIT %s""",
        (limit,),
    ).fetchall()
    for row in rows:
        row["coverage"] = coverage(row["query_stats"])
    return rows


@app.get("/api/rubric")
def rubric() -> dict:
    """Pesos y penalizaciones con los que el codigo calcula la nota de calidad."""
    data = load_rubric()
    return {"version": data["version"], "weights": data["weights"], "penalties": data["penalties"]}


@app.get("/api/facets")
def facets(conn: Reader) -> dict:
    """Valores disponibles para los filtros, con cuantos proyectos tiene cada uno."""
    currencies = conn.execute(
        "SELECT currency AS value, count(*) AS n FROM projects WHERE currency IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    languages = conn.execute(
        "SELECT language AS value, count(*) AS n FROM projects WHERE language IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    countries = conn.execute(
        f"""SELECT {MARKET_COUNTRY_SQL} AS value, count(*) AS n,
                   count(*) FILTER (WHERE c.client_country IS NOT NULL) AS mentioned
            FROM projects p
            LEFT JOIN LATERAL (SELECT client_country FROM classifications x WHERE x.project_id = p.id
                               ORDER BY x.id DESC LIMIT 1) c ON TRUE
            WHERE {MARKET_COUNTRY_SQL} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"""
    ).fetchall()
    by_region: dict[str, int] = defaultdict(int)
    for row in countries:
        row["region"] = region_for(row["value"])
        by_region[row["region"]] += row["n"]
    ordered = [{"value": name, "n": by_region.get(name, 0)} for name in [*regions(), OTHER_REGION]]
    return {"currencies": currencies, "languages": languages, "countries": countries,
            "regions": [r for r in ordered if r["n"]]}


@app.get("/api/projects")
def projects(
    conn: Reader,
    category: str | None = None,
    complexity: str | None = None,
    currency: Annotated[str | None, Query(max_length=8)] = None,
    language: Annotated[str | None, Query(max_length=8)] = None,
    country: Annotated[str | None, Query(pattern=r"^[A-Za-z]{2}$")] = None,
    region: Annotated[str | None, Query(max_length=40)] = None,
    min_relevance: Annotated[float | None, Query(ge=0, le=1)] = None,
    min_rating: Annotated[float | None, Query(ge=0, le=100)] = None,
    min_budget_usd: Annotated[float | None, Query(ge=0)] = None,
    posted_since: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    where, params = [], {"limit": limit, "offset": offset}
    if category == "sin_clasificar":
        where.append("c.category IS NULL")
    elif category:
        where.append("c.category = %(category)s")
        params["category"] = category
    if complexity:
        where.append("c.complexity = %(complexity)s")
        params["complexity"] = complexity
    if currency:
        where.append("p.currency = %(currency)s")
        params["currency"] = currency.upper()
    if language:
        where.append("p.language = %(language)s")
        params["language"] = language.lower()
    if country:
        where.append(f"{MARKET_COUNTRY_SQL} = %(country)s")
        params["country"] = country.upper()
    if region:
        if region != OTHER_REGION and region not in regions():
            raise HTTPException(422, "Región desconocida")
        where.append(_region_filter(region, params))
    if min_relevance is not None:
        where.append("c.relevance >= %(min_relevance)s")
        params["min_relevance"] = min_relevance
    if min_rating is not None:
        where.append("r.score >= %(min_rating)s")
        params["min_rating"] = min_rating
    if min_budget_usd is not None:
        where.append("COALESCE(p.budget_max, p.budget_min) * p.usd_rate >= %(min_budget_usd)s")
        params["min_budget_usd"] = min_budget_usd
    if posted_since is not None:
        where.append("p.posted_at >= %(posted_since)s")
        params["posted_since"] = posted_since
    rows, total = _query_projects(conn, where, params)
    return {"items": rows, "total": total}


@app.get("/api/projects/{project_id}")
def project_detail(project_id: int, conn: Reader) -> dict:
    project = _project_row(conn, project_id)
    project["versions"] = conn.execute(
        """SELECT pv.id, pv.changed_fields, pv.captured_at, sn.run_id
           FROM project_versions pv JOIN raw_snapshots sn ON sn.id = pv.snapshot_id
           WHERE pv.project_id = %s ORDER BY pv.id DESC""",
        (project_id,),
    ).fetchall()
    project["labels"] = conn.execute(
        "SELECT field, expected_value, author, created_at FROM labels WHERE project_id = %s ORDER BY id DESC",
        (project_id,),
    ).fetchall()
    return project


def _read_snapshot_item(file_path: str, external_id: str) -> dict | None:
    """Lee el proyecto del snapshot; solo se aceptan rutas de la carpeta de snapshots."""
    path = Path(file_path).resolve()
    if not path.is_relative_to(Path(ingest.SNAPSHOT_DIR).resolve()) or not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload["result"]["projects"]:
        if str(item.get("id")) == external_id:
            return item
    return None


@app.get("/api/projects/{project_id}/audit")
def audit(project_id: int, conn: Reader) -> dict:
    project = _project_row(conn, project_id)
    snapshot = conn.execute(
        """SELECT sn.id, sn.run_id, sn.url, sn.file_path, sn.captured_at
           FROM project_versions pv JOIN raw_snapshots sn ON sn.id = pv.snapshot_id
           WHERE pv.project_id = %s ORDER BY pv.id DESC LIMIT 1""",
        (project_id,),
    ).fetchone()
    original = _read_snapshot_item(snapshot["file_path"], project["external_id"]) if snapshot else None
    if snapshot:
        snapshot.pop("file_path")
    return {
        "fields": {name: project[name] for name in AUDIT_FIELDS},
        "snapshot": snapshot,
        "original": original,
    }


@app.post("/api/projects/{project_id}/labels", status_code=201,
          dependencies=[Depends(require_local_origin)])
def add_label(project_id: int, label: LabelIn, conn: Writer) -> dict:
    """RF-DSH-01: guarda el valor correcto; si el extraido es correcto, confirma ese valor."""
    if label.field not in (*AUDIT_FIELDS, *JUDGMENT_FIELDS):
        raise HTTPException(422, "Campo no etiquetable")
    if label.is_correct and label.field not in AUDIT_FIELDS:
        raise HTTPException(422, "Este campo necesita un valor esperado")
    if not label.is_correct and label.expected_value in (None, ""):
        raise HTTPException(422, "Indica el valor correcto")
    project = _project_row(conn, project_id)
    expected = project[label.field] if label.is_correct else label.expected_value
    row = conn.execute(
        """INSERT INTO labels (project_id, field, expected_value, author) VALUES (%s,%s,%s,%s)
           RETURNING id, field, expected_value, author, created_at""",
        (project_id, label.field, Jsonb(jsonable_encoder(expected)), label.author.strip()),
    ).fetchone()
    conn.commit()
    return row


@app.get("/api/sources")
def sources(conn: Reader) -> list[dict]:
    return conn.execute(
        """SELECT s.id, s.name, s.base_url, s.access_mode, s.legal_status, s.terms_url, s.legal_notes,
                  s.frequency, s.rate_limit_per_min, s.active,
                  r.score AS rating, r.breakdown, r.rubric_version, r.run_id AS rating_run_id,
                  (SELECT count(*) FROM projects p WHERE p.source_id = s.id) AS project_count
           FROM sources s
           LEFT JOIN LATERAL (SELECT * FROM ratings x WHERE x.target_type = 'source' AND x.target_id = s.id
                              ORDER BY x.id DESC LIMIT 1) r ON TRUE
           ORDER BY s.name"""
    ).fetchall()


def confusion_report(pairs: list[tuple[str, str]]) -> dict:
    """Matriz de confusion y precision/recall por categoria, a partir de (esperado, predicho)."""
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for expected, predicted in pairs:
        matrix[expected][predicted] += 1
    categories = sorted({c for pair in pairs for c in pair})
    per_category = {}
    for category in categories:
        true_positive = matrix[category][category]
        predicted = sum(matrix[e][category] for e in categories)
        actual = sum(matrix[category][p] for p in categories)
        per_category[category] = {
            "precision": true_positive / predicted if predicted else None,
            "recall": true_positive / actual if actual else None,
            "support": actual,
        }
    return {
        "n": len(pairs),
        "categories": categories,
        "matrix": {e: {p: matrix[e][p] for p in categories} for e in categories},
        "per_category": per_category,
    }


@app.get("/api/filter-quality")
def filter_quality(conn: Reader) -> list[dict]:
    rows = conn.execute(
        """SELECT c.prompt_version, c.category AS predicted, l.expected_value #>> '{}' AS expected
           FROM classifications c
           JOIN (SELECT DISTINCT ON (project_id) project_id, expected_value FROM labels
                 WHERE field = 'category' ORDER BY project_id, id DESC) l ON l.project_id = c.project_id
           WHERE c.category IS NOT NULL"""
    ).fetchall()
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["prompt_version"]].append((row["expected"], row["predicted"]))
    return [{"prompt_version": version, **confusion_report(pairs)} for version, pairs in sorted(
        grouped.items(), key=lambda item: str(item[0]))]


@app.get("/api/costs")
def costs(conn: Reader) -> dict:
    by_agent = conn.execute(
        """SELECT agent, model, prompt_version, count(*) AS calls,
                  COALESCE(sum(input_tokens),0) AS input_tokens, COALESCE(sum(output_tokens),0) AS output_tokens,
                  COALESCE(sum(cost_usd),0) AS cost_usd
           FROM agent_calls GROUP BY agent, model, prompt_version ORDER BY cost_usd DESC"""
    ).fetchall()
    by_run = conn.execute(
        """SELECT r.id AS run_id, s.name AS source, r.items, count(a.id) AS calls,
                  COALESCE(sum(a.input_tokens),0) AS input_tokens, COALESCE(sum(a.output_tokens),0) AS output_tokens,
                  COALESCE(sum(a.cost_usd),0) AS cost_usd
           FROM runs r JOIN sources s ON s.id = r.source_id LEFT JOIN agent_calls a ON a.run_id = r.id
           GROUP BY r.id, s.name ORDER BY r.id DESC LIMIT 50"""
    ).fetchall()
    for row in by_run:
        row["cost_per_project"] = row["cost_usd"] / row["items"] if row["items"] else None
    return {"by_agent": by_agent, "by_run": by_run}


DIAGRAMS_DIR = ROOT / ".archify"
if DIAGRAMS_DIR.is_dir():
    # Diagramas generados con Archify: http://localhost:8000/diagramas/<carpeta>/<archivo>.html
    app.mount("/diagramas", StaticFiles(directory=DIAGRAMS_DIR), name="diagramas")

if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
