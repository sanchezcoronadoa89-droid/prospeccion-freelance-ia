"""Presupuesto y borrador de propuesta para un proyecto (RF-REN-01, 02, 04 y RF-PRO-01).

Uso: python -m scripts.budget <project_id>

Reparto de trabajo, segun la regla del proyecto:
- El agente presupuestador identifica tareas y unidades (interpreta texto).
- El codigo calcula horas, coste, precio, margen y plazo con config/presupuesto.yaml.
- El agente redactor escribe el borrador usando esas cifras. Nunca se envia nada.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

import yaml
from psycopg.types.json import Jsonb

from scripts.agent_runner import AgentSpec, call_claude, load_agent
from scripts.agent_runner import _log_call as log_call
from scripts.db import ROOT, AlreadyRunning, connect, pipeline_lock

PARAMS_PATH = ROOT / "config" / "presupuesto.yaml"
SCENARIOS = ("bajo", "medio", "alto")
OTHER = "otro"
PRICE_STEP_USD = 5
DESCRIPTION_MAX_CHARS = 4000


class ProposalError(RuntimeError):
    """No se pudo generar el presupuesto; el mensaje explica por que."""


def load_params(path=PARAMS_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def parse_object(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _strings(value, limit: int) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    return [" ".join(v.split())[:300] for v in value if v.strip()][:limit]


def validate_extraction(raw: dict | None, catalog: dict) -> dict | None:
    if raw is None or not isinstance(raw.get("tasks"), list) or not isinstance(raw.get("summary"), str):
        return None
    tasks = []
    for task in raw["tasks"]:
        if not isinstance(task, dict):
            return None
        kind, units, detail = task.get("type"), task.get("units"), task.get("detail")
        if kind not in catalog and kind != OTHER:
            return None
        if isinstance(units, bool) or not isinstance(units, (int, float)) or not 0 < units <= 200:
            return None
        if not isinstance(detail, str) or not detail.strip():
            return None
        evidence = task.get("evidence") if isinstance(task.get("evidence"), str) else ""
        tasks.append({"type": kind, "units": round(float(units), 2), "detail": " ".join(detail.split())[:300],
                      "evidence": " ".join(evidence.split())[:300]})
    lists = {key: _strings(raw.get(key, []), 5) for key in ("missing_info", "questions", "red_flags")}
    if any(value is None for value in lists.values()):
        return None
    return {"summary": " ".join(raw["summary"].split())[:400], "tasks": tasks, **lists}


def compute_budget(tasks: list[dict], params: dict, budget_max_usd: float | None) -> dict:
    """Horas, coste, precio y margen por escenario. Las tareas «otro» no tienen referencia y no suman."""
    catalog, rate, commission = params["tasks"], params["hourly_rate_usd"], params["commission"]
    scenarios = {}
    for index, name in enumerate(SCENARIOS):
        hours = sum(task["units"] * catalog[task["type"]]["hours"][index] for task in tasks if task["type"] in catalog)
        cost = hours * rate
        price = cost / (1 - commission)
        net_client = budget_max_usd * (1 - commission) if budget_max_usd is not None else None
        scenarios[name] = {
            "hours": round(hours, 2),
            "cost_usd": round(cost, 2),
            "price_usd": round(price, 2),
            "margin_usd": round(net_client - cost, 2) if net_client is not None else None,
        }
    medium = scenarios["medio"]
    recommended = math.ceil(medium["price_usd"] / PRICE_STEP_USD) * PRICE_STEP_USD if medium["price_usd"] else 0
    days = max(1, math.ceil(medium["hours"] / params["hours_per_day"])) if medium["hours"] else None
    return {"scenarios": scenarios, "recommended_price_usd": recommended, "delivery_days": days}


def budget_warnings(params: dict, tasks: list[dict], budget: dict, budget_max_usd: float | None) -> list[str]:
    warnings = []
    if not params.get("calibrated"):
        warnings.append("Tarifa, comisión y horas son valores de ejemplo: calibra config/presupuesto.yaml.")
    if not tasks:
        warnings.append("No se identificó ninguna tarea: revisa la publicación a mano.")
    unpriced = [t["detail"] for t in tasks if t["type"] == OTHER]
    if unpriced:
        warnings.append(f"{len(unpriced)} tarea(s) sin referencia en la tabla de horas no suman al precio.")
    if budget_max_usd is not None and budget["recommended_price_usd"] > budget_max_usd:
        warnings.append("El precio recomendado supera el presupuesto máximo del cliente.")
    return warnings


def _call(conn, spec: AgentSpec, payload: dict, runner, validate):
    """Llama al agente, valida y reintenta una vez. Registra cada llamada en agent_calls."""
    for _ in range(2):
        reply = runner(spec, json.dumps(payload, ensure_ascii=False))
        result = validate(parse_object(reply.text)) if reply.ok else None
        log_call(conn, None, spec, reply, "ok" if result else ("error" if not reply.ok else "schema_error"))
        conn.commit()
        if result:
            return result, reply.model
    raise ProposalError(f"El agente {spec.name} no devolvió una respuesta válida tras reintentar.")


def _draft_mentions_price(draft: str, amount: int) -> bool:
    digits_only = re.sub(r"(?<=\d)[.,\s'](?=\d{3}\b)", "", draft)
    return re.search(rf"(?<!\d){amount}(?!\d)", digits_only) is not None


def generate_proposal(conn, project_id: int, *, runner=call_claude, extract_spec=None, draft_spec=None,
                      params=None) -> dict:
    params = params or load_params()
    extract_spec = extract_spec or load_agent("presupuestador")
    draft_spec = draft_spec or load_agent("redactor-propuestas")
    project = conn.execute(
        """SELECT id, title, description, skills, budget_min, budget_max, currency, usd_rate, language
           FROM projects WHERE id = %s""",
        (project_id,),
    ).fetchone()
    if project is None:
        raise ProposalError("Proyecto no encontrado")
    usd_rate = float(project["usd_rate"]) if project["usd_rate"] else None
    budget_max_usd = float(project["budget_max"]) * usd_rate if project["budget_max"] is not None and usd_rate else None
    catalog = params["tasks"]

    extraction, _ = _call(conn, extract_spec, {
        "project": {"title": project["title"], "description": (project["description"] or "")[:DESCRIPTION_MAX_CHARS],
                    "skills": project["skills"], "budget_min": _num(project["budget_min"]),
                    "budget_max": _num(project["budget_max"]), "currency": project["currency"]},
        "catalog": [{"type": key, "label": item["label"], "unit": item["unit"]} for key, item in catalog.items()],
    }, runner, lambda raw: validate_extraction(raw, catalog))

    budget = compute_budget(extraction["tasks"], params, budget_max_usd)
    recommended_usd = budget["recommended_price_usd"]
    if usd_rate and project["currency"] and project["currency"] != "USD":
        local_amount, currency = math.ceil(recommended_usd / usd_rate), project["currency"]
    else:
        local_amount, currency = int(recommended_usd), "USD"
    warnings = budget_warnings(params, extraction["tasks"], budget, budget_max_usd)

    draft, model = None, None
    if extraction["tasks"]:
        written, model = _call(conn, draft_spec, {
            "project": {"title": project["title"], "description": (project["description"] or "")[:DESCRIPTION_MAX_CHARS],
                        "language": project["language"]},
            "summary": extraction["summary"],
            "tasks": [{"label": catalog.get(t["type"], {}).get("label", t["detail"]), "units": t["units"],
                       "detail": t["detail"]} for t in extraction["tasks"]],
            "price": {"amount": local_amount, "currency": currency},
            "delivery_days": budget["delivery_days"],
            "questions": extraction["questions"][:2],
        }, runner, validate_draft)
        draft = written
        if not _draft_mentions_price(draft["proposal"], local_amount):
            warnings.append("El borrador no menciona el precio calculado: revísalo antes de usarlo.")

    row = conn.execute(
        """INSERT INTO proposals (project_id, summary, tasks, missing_info, questions, red_flags, scenarios,
               recommended_price_usd, recommended_price_local, currency, delivery_days, draft, draft_language,
               warnings, params_version, calibrated, model, prompt_version)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (project_id, extraction["summary"], Jsonb(extraction["tasks"]), Jsonb(extraction["missing_info"]),
         Jsonb(extraction["questions"]), Jsonb(extraction["red_flags"]), Jsonb(budget["scenarios"]),
         recommended_usd, local_amount, currency, budget["delivery_days"],
         draft["proposal"] if draft else None, draft["language"] if draft else None, Jsonb(warnings),
         params["version"], bool(params.get("calibrated")), model,
         f"{extract_spec.prompt_version}+{draft_spec.prompt_version}"),
    ).fetchone()
    conn.execute(
        """INSERT INTO profitability (project_id, hours_by_scenario, hourly_rate, commission, margin_by_scenario,
               params_version, model) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (project_id, Jsonb({k: v["hours"] for k, v in budget["scenarios"].items()}), params["hourly_rate_usd"],
         params["commission"], Jsonb({k: v["margin_usd"] for k, v in budget["scenarios"].items()}),
         params["version"], model),
    )
    conn.commit()
    return row


def validate_draft(raw: dict | None) -> dict | None:
    if raw is None:
        return None
    proposal, language = raw.get("proposal"), raw.get("language")
    if not isinstance(proposal, str) or not 200 <= len(proposal.strip()) <= 3000:
        return None
    if not isinstance(language, str) or not 2 <= len(language) <= 8:
        return None
    return {"proposal": proposal.strip(), "language": language.lower()}


def _num(value):
    return float(value) if value is not None else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Presupuesto y borrador de propuesta para un proyecto")
    parser.add_argument("project_id", type=int)
    args = parser.parse_args(argv)
    with connect() as conn:
        try:
            with pipeline_lock(conn, f"propuesta-{args.project_id}"):
                row = generate_proposal(conn, args.project_id)
        except (AlreadyRunning, ProposalError) as exc:
            print(json.dumps({"status": "error", "motivo": str(exc)}, ensure_ascii=False))
            return 3
    print(json.dumps(row, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
