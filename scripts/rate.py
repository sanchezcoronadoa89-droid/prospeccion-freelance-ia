"""/rate [corrida]: rating de posts y de fuentes (RF-RAT-01 a 03).

Uso: python -m scripts.rate [corrida] [--limit N] [--include-golden]
El agente puntua criterios; todas las notas se calculan aqui.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

import yaml
from psycopg.types.json import Jsonb

from scripts.agent_runner import (call_claude, content_hash, load_agent, load_pipeline_config,
                                  process_in_batches)
from scripts.classify import golden_project_ids, latest_run_id
from scripts.db import ROOT, AlreadyRunning, connect, pipeline_lock

RUBRIC_PATH = ROOT / "config" / "rubrica_calidad_v1.yaml"
CRITERIA = ("scope", "deliverables", "budget", "timeline")
FLAGS = ("free_work", "off_platform")


def load_rubric(path=RUBRIC_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def post_score(result: dict, rubric: dict) -> float:
    """Nota de 0 a 100: media ponderada de criterios menos penalizaciones."""
    weights = rubric["weights"]
    earned = sum(weights[c] * result[c] / 5 for c in CRITERIA) / sum(weights.values()) * 100
    earned -= sum(rubric["penalties"][f] for f in FLAGS if result[f])
    return round(max(0.0, min(100.0, earned)), 2)


def validate_rating(raw: dict) -> dict | None:
    for criterion in CRITERIA:
        value = raw.get(criterion)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5:
            return None
    if not all(isinstance(raw.get(f), bool) for f in FLAGS):
        return None
    notes = raw.get("notes")
    if not isinstance(notes, str) or not notes.strip():
        return None
    return {**{c: raw[c] for c in CRITERIA}, **{f: raw[f] for f in FLAGS}, "notes": " ".join(notes.split())[:300]}


def source_score(components: dict, rubric: dict) -> float:
    weights = rubric["source_weights"]
    score = sum(weights[name] * components[name] for name in weights) / sum(weights.values()) * 100
    return round(score, 2)


def rate_sources(conn, run_id: int, rubric: dict, threshold: float) -> int:
    """RF-RAT-02: en codigo. Una fuente no permitida puntua 0, sea cual sea su calidad."""
    rated = 0
    for source in conn.execute("SELECT id, legal_status FROM sources").fetchall():
        row = conn.execute(
            """SELECT count(*) AS total,
                      count(*) FILTER (WHERE c.relevance >= %s) AS relevant,
                      avg(r.score) AS mean_quality
               FROM projects p
               JOIN LATERAL (SELECT relevance FROM classifications x WHERE x.project_id = p.id
                             ORDER BY x.id DESC LIMIT 1) c ON TRUE
               LEFT JOIN LATERAL (SELECT score FROM ratings x WHERE x.target_type = 'post' AND x.target_id = p.id
                                  ORDER BY x.id DESC LIMIT 1) r ON TRUE
               WHERE p.source_id = %s""",
            (threshold, source["id"]),
        ).fetchone()
        if not row["total"]:
            continue
        budgets = [float(b["usd"]) for b in conn.execute(
            """SELECT (COALESCE(budget_min, budget_max) + COALESCE(budget_max, budget_min)) / 2 * usd_rate AS usd
               FROM projects WHERE source_id = %s AND usd_rate IS NOT NULL
                 AND COALESCE(budget_min, budget_max) IS NOT NULL""",
            (source["id"],),
        ).fetchall()]
        weekly = conn.execute(
            "SELECT count(*) AS n FROM projects WHERE source_id = %s AND first_seen_at > now() - interval '7 days'",
            (source["id"],),
        ).fetchone()["n"]
        ingest = conn.execute(
            "SELECT coalesce(sum(items),0) AS items, coalesce(sum(error_count),0) AS errors FROM runs WHERE source_id = %s",
            (source["id"],),
        ).fetchone()
        attempts = ingest["items"] + ingest["errors"]
        components = {
            "relevant_share": row["relevant"] / row["total"],
            "mean_quality": float(row["mean_quality"] or 0) / 100,
            "ingest_success": ingest["items"] / attempts if attempts else 0.0,
        }
        allowed = source["legal_status"] == "permitido"
        breakdown = {**{k: round(v, 3) for k, v in components.items()},
                     "median_budget_usd": round(statistics.median(budgets), 2) if budgets else None,
                     "weekly_volume": weekly, "legal_status": source["legal_status"]}
        conn.execute(
            """INSERT INTO ratings (target_type, target_id, run_id, score, breakdown, rubric_version)
               VALUES ('source', %s, %s, %s, %s, %s)""",
            (source["id"], run_id, source_score(components, rubric) if allowed else 0, Jsonb(breakdown),
             rubric["version"]),
        )
        rated += 1
    conn.commit()
    return rated


def run_rate(conn, run_id=None, *, limit=None, include_golden=False, runner=call_claude,
             spec=None, config=None, rubric=None) -> dict:
    spec = spec or load_agent("evaluador-calidad")
    config = config or load_pipeline_config()
    rubric = rubric or load_rubric()
    run_id = run_id or latest_run_id(conn)
    reserved = set() if include_golden else golden_project_ids(conn)
    threshold = config["relevance_threshold"]
    rows = conn.execute(
        """SELECT p.id, p.title, p.description, p.skills, p.budget_min, p.budget_max, p.currency, p.project_type
           FROM projects p
           JOIN LATERAL (SELECT relevance FROM classifications x WHERE x.project_id = p.id
                         ORDER BY x.id DESC LIMIT 1) c ON TRUE
           WHERE c.relevance >= %s ORDER BY p.id""",
        (threshold,),
    ).fetchall()
    done = {(r["target_id"], r["content_hash"], r["prompt_version"], r["rubric_version"]) for r in conn.execute(
        "SELECT target_id, content_hash, prompt_version, rubric_version FROM ratings WHERE target_type = 'post'"
    ).fetchall()}

    def digest(project):
        return content_hash(project["title"], project["description"], project["budget_min"], project["budget_max"])

    pending = [p for p in rows if p["id"] not in reserved
               and (p["id"], digest(p), spec.prompt_version, rubric["version"]) not in done]
    if limit is not None:
        pending = pending[:limit]
    max_chars = config["description_max_chars"]

    def build_item(project):
        return {"id": project["id"], "title": project["title"],
                "description": (project["description"] or "")[:max_chars], "skills": project["skills"],
                "budget_min": float(project["budget_min"]) if project["budget_min"] is not None else None,
                "budget_max": float(project["budget_max"]) if project["budget_max"] is not None else None,
                "currency": project["currency"], "project_type": project["project_type"]}

    def save(project, result, model):
        conn.execute(
            """INSERT INTO ratings (target_type, target_id, run_id, score, breakdown, rubric_version, model,
                   prompt_version, content_hash) VALUES ('post', %s, %s, %s, %s, %s, %s, %s, %s)""",
            (project["id"], run_id, post_score(result, rubric), Jsonb(result), rubric["version"], model,
             spec.prompt_version, digest(project)),
        )

    stats = process_in_batches(
        conn, spec, pending, run_id=run_id, build_item=build_item, validate=validate_rating, save=save,
        give_up=lambda project: None, batch_size=config["batch_size"],
        max_cost_usd=config["max_cost_per_run_usd"], runner=runner,
    )
    sources = rate_sources(conn, run_id, rubric, threshold)
    return {"run_id": run_id, "prompt_version": spec.prompt_version, "rubric": rubric["version"],
            "sent_to_llm": len(pending), "sources_rated": sources, **stats}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Puntua posts y fuentes")
    parser.add_argument("run", nargs="?", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-golden", action="store_true")
    args = parser.parse_args(argv)
    with connect() as conn:
        try:
            with pipeline_lock(conn):
                result = run_rate(conn, args.run, limit=args.limit, include_golden=args.include_golden)
        except AlreadyRunning as exc:
            print(json.dumps({"status": "ocupado", "motivo": str(exc)}, ensure_ascii=False))
            return 4
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not result["stopped_by_budget"] else 3


if __name__ == "__main__":
    sys.exit(main())
