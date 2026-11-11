"""Etiquetado a ciegas del golden set y calculo de acuerdo (fase 0)."""
import json
import random
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from dashboard.api.deps import Reader, Writer, require_local_origin
from evals.kappa import cohen_kappa, weighted_kappa
from scripts.db import ROOT

GOLDEN_DIR = ROOT / "evals" / "golden"
VERSION = "v2"
KAPPA_THRESHOLD = 0.6
FIELDS = ("category", "relevant", "complexity", "quality")
COMPLEXITY_LEVELS = {"baja": 1, "media": 2, "alta": 3}

router = APIRouter(prefix="/api/golden")
Author = Annotated[str, Query(min_length=1, max_length=80)]


def normalize_author(author: str) -> str:
    return " ".join(author.lower().split())


def load_sample() -> dict | None:
    path = Path(GOLDEN_DIR) / f"sample_{VERSION}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def require_sample() -> dict:
    sample = load_sample()
    if sample is None:
        raise HTTPException(404, "Aún no se ha generado la muestra del golden set")
    return sample


def _projects(conn, sample: dict) -> list[dict]:
    """Proyectos de la muestra en el orden del archivo, con su division."""
    rows = conn.execute(
        """SELECT p.id, s.name AS source, p.external_id, p.title, p.description, p.skills, p.budget_min,
                  p.budget_max, p.currency, p.project_type, p.url
           FROM projects p JOIN sources s ON s.id = p.source_id"""
    ).fetchall()
    index = {(r["source"], r["external_id"]): r for r in rows}
    found = []
    for item in sample["items"]:
        project = index.get((item["source"], item["external_id"]))
        if project:
            found.append({**project, "split": item["split"]})
    return found


def _order(projects: list[dict], label_pass: int) -> list[dict]:
    """La segunda pasada usa otro orden para no recordar la secuencia."""
    if label_pass == 1:
        return projects
    shuffled = projects[:]
    random.Random(f"{VERSION}:2").shuffle(shuffled)
    return shuffled


def _labels(conn, author: str | None = None) -> list[dict]:
    query = """SELECT project_id, field, expected_value, author, label_pass, created_at FROM labels
               WHERE golden_version = %s"""
    params = [VERSION]
    if author:
        query += " AND author = %s"
        params.append(author)
    return conn.execute(query, params).fetchall()


def _state(conn, sample: dict, author: str, now: datetime | None = None) -> dict:
    """Decide la pasada actual y si la segunda ya se puede empezar."""
    now = now or datetime.now(timezone.utc)
    projects = _projects(conn, sample)
    labels = [l for l in _labels(conn, author) if l["field"] == "category"]
    done = {1: {l["project_id"] for l in labels if l["label_pass"] == 1},
            2: {l["project_id"] for l in labels if l["label_pass"] == 2}}
    ids = {p["id"] for p in projects}
    state = {"total": len(projects), "done_pass1": len(done[1] & ids), "done_pass2": len(done[2] & ids),
             "available_at": None, "projects": projects}
    if not ids - done[1]:
        last = max((l["created_at"] for l in labels if l["label_pass"] == 1), default=now)
        available = last + timedelta(days=sample["min_days_between_passes"])
        if not ids - done[2]:
            state.update(status="done", label_pass=None)
        elif now < available:
            state.update(status="wait", label_pass=2, available_at=available)
        else:
            state.update(status="label", label_pass=2)
    else:
        state.update(status="label", label_pass=1)
    state["pending"] = done
    return state


@router.get("/next")
def next_item(author: Author, conn: Reader) -> dict:
    """Siguiente proyecto a etiquetar. Nunca devuelve las respuestas de otra pasada."""
    sample = load_sample()
    if sample is None:
        return {"status": "no_sample"}
    author = normalize_author(author)
    state = _state(conn, sample, author)
    item = None
    if state["status"] == "label":
        answered = state["pending"][state["label_pass"]]
        item = next((p for p in _order(state["projects"], state["label_pass"]) if p["id"] not in answered), None)
    return {
        "status": state["status"], "label_pass": state["label_pass"], "total": state["total"],
        "done_pass1": state["done_pass1"], "done_pass2": state["done_pass2"],
        "available_at": state["available_at"], "item": item,
    }


@router.get("/rubric")
def rubric() -> dict:
    sample = require_sample()
    text = (Path(GOLDEN_DIR) / sample["rubric"]).read_text(encoding="utf-8")
    return {"file": sample["rubric"], "text": text}


class GoldenLabel(BaseModel):
    project_id: int
    author: str = Field(min_length=1, max_length=80)
    category: Literal["marketing", "seo", "ia_automatizacion", "web_simple", "ux_ui", "otra"]
    relevant: bool
    complexity: Literal["baja", "media", "alta"]
    quality: int = Field(ge=1, le=5)

    @field_validator("author")
    @classmethod
    def clean_author(cls, value: str) -> str:
        cleaned = normalize_author(value)
        if not cleaned:
            raise ValueError("Indica tu nombre")
        return cleaned


@router.post("/labels", status_code=201, dependencies=[Depends(require_local_origin)])
def save_label(label: GoldenLabel, conn: Writer) -> dict:
    """Guarda las tres etiquetas de un proyecto en la pasada que le toca a esa persona."""
    sample = require_sample()
    state = _state(conn, sample, label.author)
    if state["status"] != "label":
        raise HTTPException(409, "Ahora mismo no hay ninguna pasada abierta")
    project = next((p for p in state["projects"] if p["id"] == label.project_id), None)
    if project is None:
        raise HTTPException(422, "El proyecto no pertenece a la muestra")
    if label.project_id in state["pending"][state["label_pass"]]:
        raise HTTPException(409, "Este proyecto ya está etiquetado en esta pasada")
    for field in FIELDS:
        conn.execute(
            """INSERT INTO labels (project_id, field, expected_value, author, dataset_split, golden_version, label_pass)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (label.project_id, field, Jsonb(getattr(label, field)), label.author, project["split"],
             VERSION, state["label_pass"]),
        )
    conn.commit()
    return {"label_pass": state["label_pass"]}


def compare_sessions(first: dict[int, dict], second: dict[int, dict]) -> dict:
    """Acuerdo entre dos sesiones completas: {project_id: {campo: valor}}."""
    ids = sorted(first.keys() & second.keys())
    values = {f: ([first[i][f] for i in ids], [second[i][f] for i in ids]) for f in FIELDS}
    kappas = {
        "category": cohen_kappa(*values["category"]),
        "relevant": cohen_kappa(*values["relevant"]),
        # Complejidad y calidad son escalas ordenadas: la puerta usa pesos cuadraticos.
        "complexity": weighted_kappa(*[[COMPLEXITY_LEVELS[v] for v in side] for side in values["complexity"]],
                                     scale=(1, 3)),
        "quality": weighted_kappa(*values["quality"]),
    }
    return {
        "n": len(ids),
        "kappa": kappas,
        "quality_unweighted_kappa": cohen_kappa(*values["quality"]),
        "raw_agreement": {f: sum(x == y for x, y in zip(*values[f])) / len(ids) for f in FIELDS},
        "passes": all(value >= KAPPA_THRESHOLD for value in kappas.values()),
        "disagreements": [
            {"project_id": i, "field": f, "first": first[i][f], "second": second[i][f]}
            for i in ids for f in FIELDS if first[i][f] != second[i][f]
        ],
    }


@router.get("/agreement")
def agreement(conn: Reader) -> dict:
    """Solo compara sesiones terminadas: antes de eso no se revela ningun resultado."""
    sample = load_sample()
    if sample is None:
        return {"threshold": KAPPA_THRESHOLD, "comparisons": []}
    expected = {p["id"]: p["title"] for p in _projects(conn, sample)}
    sessions: dict[tuple[str, int], dict[int, dict]] = {}
    for label in _labels(conn):
        if label["project_id"] in expected:
            session = sessions.setdefault((label["author"], label["label_pass"]), {})
            session.setdefault(label["project_id"], {})[label["field"]] = label["expected_value"]
    complete = {key: answers for key, answers in sessions.items()
                if expected and expected.keys() <= answers.keys()
                and all(len(a) == len(FIELDS) for a in answers.values())}
    comparisons = []
    for a, b in combinations(sorted(complete), 2):
        report = compare_sessions(complete[a], complete[b])
        for row in report["disagreements"]:
            row["title"] = expected[row["project_id"]]
        comparisons.append({"first": {"author": a[0], "label_pass": a[1]},
                            "second": {"author": b[0], "label_pass": b[1]},
                            "same_person": a[0] == b[0], **report})
    return {"threshold": KAPPA_THRESHOLD, "comparisons": comparisons}
