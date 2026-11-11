"""/eval <etapa>: compara agentes con el golden set y con la ultima linea base.

Uso: python -m evals.run classify|rate [--split dev|test]
Los prompts se ajustan solo contra dev. Una caida de mas de 2 puntos no se adopta sin explicarla.
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dashboard.api.main import confusion_report
from scripts.db import ROOT, connect

RESULTS_DIR = ROOT / "evals" / "results"
MAX_DROP = 0.02
THRESHOLDS = {"classify": {"relevant_precision": 0.90, "relevant_recall": 0.85},
              "rate": {"spearman": 0.6, "within_one_point": 0.80}}
RELEVANCE_CUTOFF = 0.5


def _ranks(values: list[float]) -> list[float]:
    """Rangos con empates promediados."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        for index in order[position:end + 1]:
            ranks[index] = (position + end) / 2 + 1
        position = end + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) != len(b) or len(a) < 2:
        return None
    ra, rb = _ranks(a), _ranks(b)
    mean_a, mean_b = sum(ra) / len(ra), sum(rb) / len(rb)
    numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(ra, rb))
    denominator = (sum((x - mean_a) ** 2 for x in ra) * sum((y - mean_b) ** 2 for y in rb)) ** 0.5
    return numerator / denominator if denominator else None


def score_to_scale(score: float) -> float:
    """Convierte la nota 0-100 del agente a la escala humana 1-5."""
    return 1 + float(score) / 25


def relevance_metrics(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs: (esperado, predicho)."""
    true_positive = sum(e and p for e, p in pairs)
    predicted = sum(p for _, p in pairs)
    actual = sum(e for e, _ in pairs)
    return {"relevant_precision": true_positive / predicted if predicted else None,
            "relevant_recall": true_positive / actual if actual else None}


def golden_labels(conn, field: str, split: str) -> dict[int, object]:
    """Etiqueta de la primera pasada; si no existe, la de la segunda."""
    rows = conn.execute(
        """SELECT DISTINCT ON (project_id) project_id, expected_value FROM labels
           WHERE field = %s AND dataset_split = %s AND golden_version IS NOT NULL
           ORDER BY project_id, label_pass, id""",
        (field, split),
    ).fetchall()
    return {r["project_id"]: r["expected_value"] for r in rows}


def eval_classify(conn, split: str) -> dict:
    rows = conn.execute(
        """SELECT DISTINCT ON (project_id) project_id, category, relevance, prompt_version FROM classifications
           WHERE category IS NOT NULL ORDER BY project_id, id DESC"""
    ).fetchall()
    predicted = {r["project_id"]: r for r in rows}
    categories, relevant = golden_labels(conn, "category", split), golden_labels(conn, "relevant", split)
    ids = sorted(categories.keys() & relevant.keys() & predicted.keys())
    report = confusion_report([(categories[i], predicted[i]["category"]) for i in ids]) if ids else {"n": 0}
    metrics = relevance_metrics([(bool(relevant[i]), float(predicted[i]["relevance"]) >= RELEVANCE_CUTOFF) for i in ids])
    return {"n": len(ids), "metrics": metrics, "confusion": report,
            "versions": sorted({str(predicted[i]["prompt_version"]) for i in ids})}


def eval_rate(conn, split: str) -> dict:
    rows = conn.execute(
        """SELECT DISTINCT ON (target_id) target_id, score, rubric_version FROM ratings
           WHERE target_type = 'post' ORDER BY target_id, id DESC"""
    ).fetchall()
    predicted = {r["target_id"]: r for r in rows}
    quality = golden_labels(conn, "quality", split)
    ids = sorted(quality.keys() & predicted.keys())
    human = [float(quality[i]) for i in ids]
    model = [score_to_scale(predicted[i]["score"]) for i in ids]
    within = sum(abs(h - m) <= 1 for h, m in zip(human, model)) / len(ids) if ids else None
    return {"n": len(ids), "metrics": {"spearman": spearman(human, model), "within_one_point": within},
            "versions": sorted({predicted[i]["rubric_version"] for i in ids})}


def compare_with_baseline(stage: str, split: str, metrics: dict, results_dir=RESULTS_DIR) -> list[str]:
    """Metricas que caen mas de 2 puntos frente al ultimo resultado guardado."""
    files = sorted(Path(results_dir).glob(f"{stage}_{split}_*.json"))
    if not files:
        return []
    previous = json.loads(files[-1].read_text(encoding="utf-8"))["metrics"]
    return [name for name, value in metrics.items()
            if value is not None and previous.get(name) is not None and previous[name] - value > MAX_DROP]


def run(conn, stage: str, split: str, results_dir=RESULTS_DIR) -> dict:
    result = (eval_classify if stage == "classify" else eval_rate)(conn, split)
    thresholds = THRESHOLDS[stage]
    result.update(
        stage=stage, split=split,
        passes={k: (result["metrics"][k] is not None and result["metrics"][k] >= v) for k, v in thresholds.items()},
        regressions=compare_with_baseline(stage, split, result["metrics"], results_dir),
    )
    if result["n"]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        Path(results_dir, f"{stage}_{split}_{stamp}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evalua una etapa contra el golden set")
    parser.add_argument("stage", choices=["classify", "rate"])
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    args = parser.parse_args(argv)
    with connect() as conn:
        result = run(conn, args.stage, args.split)
    summary = {k: result[k] for k in ("stage", "split", "n", "metrics", "passes", "regressions")}
    if not result["n"]:
        summary["motivo"] = ("Sin datos: faltan etiquetas del golden set o resultados del agente sobre esos proyectos. "
                             "Tras etiquetar, ejecuta el agente con --include-golden.")
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return 0 if result["n"] and all(result["passes"].values()) and not result["regressions"] else 3


if __name__ == "__main__":
    sys.exit(main())
