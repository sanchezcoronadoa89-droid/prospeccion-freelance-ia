"""/classify [corrida]: reglas primero y LLM para el resto (RF-CLA-01 a 03).

Uso: python -m scripts.classify [corrida] [--limit N] [--include-golden]
Los proyectos del golden set se reservan hasta terminar de etiquetarlos.
"""
import argparse
import json
import re
import sys
from functools import cache

import yaml
from psycopg.types.json import Jsonb

from dashboard.api import golden
from scripts.registry import PROFILES_PATH
from scripts.agent_runner import (call_claude, content_hash, load_agent, load_pipeline_config,
                                  process_in_batches)
from scripts.db import AlreadyRunning, connect, pipeline_lock

RULES_VERSION = "reglas-v2"
CATEGORIES = {"marketing", "seo", "ia_automatizacion", "web_simple", "ux_ui", "otra"}
COMPLEXITY = {"baja", "media", "alta"}
COUNTRY_RE = re.compile(r"^[A-Za-z]{2}$")
# La regla solo decide cuando no hay ninguna skill del perfil ni ninguna de estas palabras en el
# titulo, la descripcion o las skills. Lo dudoso va al LLM. Medida el 11 nov 2026 contra 1.171
# clasificaciones de la IA: descarta un 5 % sin perder ningun proyecto relevante. "design" no esta
# a proposito: es lo que permite descartar interiorismo, planos o packaging.
TOPIC = re.compile(
    r"\b(seo|search engine|keywords?|backlinks?|serp|ux|ui|usability|figma|wireframes?|prototyp\w*|"
    r"marketing|analytics?|analysis|anal[ií]tica|reporting|dashboards?|looker|power bi|ads|adwords|advertis\w*|"
    r"ppc|tag manager|gtm|ga4|pixel|tracking|conversions?|conversi[oó]n|leads?|email|newsletter|crm|hubspot|"
    r"copywriting|copywriter|content|contenido|conte[uú]do|blog\w*|social|instagram|facebook|tiktok|linkedin|"
    r"reddit|youtube|influencer|community|brand\w*|marca|campa\w+|campaign\w*|growth|sales|ventas|"
    r"chatbots?|bots?|automat\w*|n8n|zapier|make\.com|ai|ia|gpt|chatgpt|llm|openai|agents?|machine learning|"
    r"landing|wordpress|shopify|woocommerce|webflow|wix|websites?|web|sitio|p[aá]gina|site|online store|"
    r"tienda|loja|e-?commerce|posicionamiento|publicidad|anuncios|tr[aá]fego|otimiza\w*|optimi[sz]\w*|"
    r"presentaci\w+|api)\b"
)


@cache
def profile_skills() -> frozenset[str]:
    profiles = yaml.safe_load(PROFILES_PATH.read_text(encoding="utf-8"))["profiles"]
    return frozenset(name.lower() for profile in profiles.values() for name in profile.get("job_names", []))


def project_hash(project: dict) -> str:
    return content_hash(project["title"], project["description"], project["skills"])


def rule_classify(project: dict) -> dict | None:
    """Decide solo lo claramente ajeno al perfil (RF-CLA-02)."""
    if {skill.lower() for skill in project["skills"]} & profile_skills():
        return None
    text = f"{project['title']} {project['description'] or ''} {' '.join(project['skills'])}".lower()
    if TOPIC.search(text):
        return None
    return {"category": "otra", "subcategories": [], "language": None, "relevance": 0.0, "complexity": None,
            "justification": "Sin skills del perfil ni ninguna señal de marketing, SEO, IA, web o UX/UI."}


def validate_classification(raw: dict) -> dict | None:
    relevance = raw.get("relevance")
    justification = raw.get("justification")
    subcategories = raw.get("subcategories", [])
    language = raw.get("language")
    country = raw.get("client_country")
    if country is not None and (not isinstance(country, str) or not COUNTRY_RE.match(country)):
        return None
    if (raw.get("category") not in CATEGORIES or raw.get("complexity") not in COMPLEXITY
            or isinstance(relevance, bool) or not isinstance(relevance, (int, float)) or not 0 <= relevance <= 1
            or not isinstance(justification, str) or not justification.strip()
            or not isinstance(subcategories, list) or not all(isinstance(s, str) for s in subcategories)
            or not isinstance(language, str) or not 2 <= len(language) <= 8):
        return None
    return {"category": raw["category"], "subcategories": subcategories[:3], "language": language.lower(),
            "relevance": round(float(relevance), 3), "complexity": raw["complexity"],
            "client_country": country.upper() if country else None,
            "justification": " ".join(justification.split())[:300]}


def golden_project_ids(conn) -> set[int]:
    sample = golden.load_sample()
    if sample is None:
        return set()
    wanted = {(i["source"], i["external_id"]) for i in sample["items"]}
    rows = conn.execute(
        "SELECT p.id, s.name, p.external_id FROM projects p JOIN sources s ON s.id = p.source_id").fetchall()
    return {r["id"] for r in rows if (r["name"], r["external_id"]) in wanted}


def latest_run_id(conn) -> int:
    row = conn.execute("SELECT max(id) AS id FROM runs WHERE status IN ('ok','parcial')").fetchone()
    if row["id"] is None:
        raise SystemExit("No hay ninguna corrida de ingesta valida")
    return row["id"]


def _insert(conn, project_id, run_id, result, digest, model, prompt_version, needs_review=False) -> None:
    conn.execute(
        """INSERT INTO classifications (project_id, run_id, category, subcategories, language, relevance,
               complexity, client_country, justification, needs_review, model, prompt_version, content_hash)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (project_id, run_id, result["category"], Jsonb(result["subcategories"]), result["language"],
         result["relevance"], result["complexity"], result.get("client_country"), result["justification"], needs_review, model,
         prompt_version, digest),
    )


def run_classify(conn, run_id=None, *, limit=None, include_golden=False, runner=call_claude,
                 spec=None, config=None) -> dict:
    spec = spec or load_agent("clasificador")
    config = config or load_pipeline_config()
    run_id = run_id or latest_run_id(conn)
    reserved = set() if include_golden else golden_project_ids(conn)
    projects = conn.execute(
        "SELECT id, title, description, skills FROM projects WHERE near_duplicate_of IS NULL ORDER BY id"
    ).fetchall()
    done = {(r["project_id"], r["content_hash"], r["prompt_version"]) for r in conn.execute(
        "SELECT project_id, content_hash, prompt_version FROM classifications").fetchall()}
    classified_content = {(project_id, digest) for project_id, digest, _ in done}

    by_rules, for_llm = 0, []
    for project in projects:
        if project["id"] in reserved:
            continue
        digest = project_hash(project)
        decided = rule_classify(project)
        if decided is not None:
            # Si ya tiene una clasificacion para este mismo contenido, no se sustituye por la regla.
            if (project["id"], digest) not in classified_content:
                _insert(conn, project["id"], run_id, decided, digest, None, RULES_VERSION)
                by_rules += 1
        elif (project["id"], digest, spec.prompt_version) not in done:
            for_llm.append(project)
    conn.commit()
    if limit is not None:
        for_llm = for_llm[:limit]

    max_chars = config["description_max_chars"]

    def build_item(project):
        return {"id": project["id"], "title": project["title"],
                "description": (project["description"] or "")[:max_chars], "skills": project["skills"]}

    def save(project, result, model):
        _insert(conn, project["id"], run_id, result, project_hash(project), model, spec.prompt_version)

    def give_up(project):
        result = {"category": None, "subcategories": [], "language": None, "relevance": None, "complexity": None,
                  "justification": "Salida del modelo no valida tras reintentar: a revisar."}
        _insert(conn, project["id"], run_id, result, project_hash(project), None, spec.prompt_version, True)

    stats = process_in_batches(
        conn, spec, for_llm, run_id=run_id, build_item=build_item, validate=validate_classification,
        save=save, give_up=give_up, batch_size=config["batch_size"],
        max_cost_usd=config["max_cost_per_run_usd"], runner=runner,
    )
    return {"run_id": run_id, "prompt_version": spec.prompt_version, "by_rules": by_rules,
            "reserved_golden": len(reserved), "sent_to_llm": len(for_llm), **stats}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Clasifica proyectos")
    parser.add_argument("run", nargs="?", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-golden", action="store_true")
    args = parser.parse_args(argv)
    with connect() as conn:
        try:
            with pipeline_lock(conn):
                result = run_classify(conn, args.run, limit=args.limit, include_golden=args.include_golden)
        except AlreadyRunning as exc:
            print(json.dumps({"status": "ocupado", "motivo": str(exc)}, ensure_ascii=False))
            return 4
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not result["stopped_by_budget"] else 3


if __name__ == "__main__":
    sys.exit(main())
