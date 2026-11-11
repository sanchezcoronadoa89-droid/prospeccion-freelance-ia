"""Genera la muestra fija del golden set. Uso: python -m scripts.golden_sample v2

La muestra no se regenera: cambiarla exige una version nueva.
"""
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from scripts.db import ROOT, connect

GOLDEN_DIR = ROOT / "evals" / "golden"
SEED = 20261106
DEV_SHARE = 0.7
MIN_DAYS_BETWEEN_PASSES = 7
# Cuantos proyectos tomar por estrato; lo que falte se completa con el resto.
QUOTAS = {"idioma_es": 20, "idioma_pt": 10, "senal_marketing": 40, "senal_ia": 30, "senal_seo": 30,
          "senal_web": 20, "senal_ux": 15, "negativo_dificil": 25, "sin_senal": 10}
TOTAL = 200
TEXT_SIGNAL = re.compile(r"\b(ux|ui|user experience|wireframes?|figma|prototype|usability|seo|search engine|"
                         r"keyword research|backlinks?|serp|marketing|analytics|ads|automation|chatbot|ai)\b")
SKILL_STRATA = (
    ("senal_ia", re.compile(r"\bai\b|artificial intelligence|automation|chatbot|n8n|zapier|\bgpt\b|llm|machine learning")),
    ("senal_seo", re.compile(r"seo|search engine|link building|keyword research")),
    ("senal_marketing", re.compile(r"marketing|\bads\b|advertis|\bppc\b|analytics|tag manager|lead generation|"
                                   r"copywriting|content|social media")),
    ("senal_ux", re.compile(r"\bux\b|\bui\b|user (experience|interface)|figma|wirefram")),
    ("senal_web", re.compile(r"web design|website design|wordpress|shopify|woocommerce|webflow|\bwix\b|landing")),
)


def stratum(project: dict, language: str | None) -> str:
    if language in ("es", "pt"):
        return f"idioma_{language}"
    skills = " ".join(project["skills"]).lower()
    for name, pattern in SKILL_STRATA:
        if pattern.search(skills):
            return name
    text = f"{project['title']} {project['description'] or ''}".lower()
    return "negativo_dificil" if TEXT_SIGNAL.search(text) else "sin_senal"


def languages_from_snapshots(conn) -> dict[str, str | None]:
    """El idioma solo esta en los snapshots; la tabla projects no lo guarda."""
    languages = {}
    for row in conn.execute("SELECT DISTINCT file_path FROM raw_snapshots").fetchall():
        payload = json.loads(Path(row["file_path"]).read_text(encoding="utf-8"))
        for item in payload["result"]["projects"]:
            languages[str(item.get("id"))] = item.get("language")
    return languages


def build_sample(projects: list[dict], languages: dict, version: str, total: int = TOTAL) -> dict:
    rng = random.Random(SEED)
    groups = defaultdict(list)
    for project in sorted(projects, key=lambda p: (p["source"], p["external_id"])):
        groups[stratum(project, languages.get(project["external_id"]))].append(project)
    chosen, leftovers = [], []
    for name, quota in QUOTAS.items():
        members = groups.get(name, [])[:]
        rng.shuffle(members)
        chosen += [(name, project) for project in members[:quota]]
        leftovers += [(name, project) for project in members[quota:]]
    rng.shuffle(leftovers)
    chosen += leftovers[:max(0, total - len(chosen))]
    chosen = chosen[:total]

    by_stratum = defaultdict(list)
    for name, project in chosen:
        by_stratum[name].append(project)
    items = []
    for name, members in by_stratum.items():
        cut = round(len(members) * DEV_SHARE)
        items += [{"source": p["source"], "external_id": p["external_id"], "stratum": name,
                   "split": "dev" if i < cut else "test"} for i, p in enumerate(members)]
    rng.shuffle(items)
    return {
        "version": version,
        "seed": SEED,
        "rubric": f"rubrica_{version}.md",
        "min_days_between_passes": MIN_DAYS_BETWEEN_PASSES,
        "items": items,
    }


def main(version: str) -> int:
    path = GOLDEN_DIR / f"sample_{version}.json"
    if path.exists():
        print(f"{path.name} ya existe: la muestra es fija. Usa una version nueva para cambiarla.")
        return 1
    with connect() as conn:
        projects = conn.execute(
            """SELECT s.name AS source, p.external_id, p.title, p.description, p.skills
               FROM projects p JOIN sources s ON s.id = p.source_id"""
        ).fetchall()
        sample = build_sample(projects, languages_from_snapshots(conn), version)
    path.write_text(json.dumps(sample, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({
        "archivo": path.name, "total": len(sample["items"]),
        "estratos": Counter(i["stratum"] for i in sample["items"]),
        "division": Counter(i["split"] for i in sample["items"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "v2"))
