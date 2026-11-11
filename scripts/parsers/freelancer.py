"""Parser determinista: de un proyecto de la API a la forma normalizada (RF-ING-04)."""
from datetime import datetime, timedelta, timezone

REQUIRED_FIELDS = ("external_id", "title", "url", "project_type", "currency", "posted_at", "budget_min")
TYPES = {"fixed": "fixed", "hourly": "hourly"}


def parse_project(raw: dict, base_url: str) -> dict:
    currency = raw.get("currency") or {}
    budget = raw.get("budget") or {}
    seo_url = raw.get("seo_url")
    submitted = raw.get("submitdate")
    return {
        "external_id": str(raw["id"]) if raw.get("id") is not None else None,
        "url": f"{base_url.rstrip('/')}/projects/{seo_url}" if seo_url else None,
        "title": raw.get("title") or None,
        "description": raw.get("description") or raw.get("preview_description"),
        "skills": [j["name"] for j in raw.get("jobs") or [] if j.get("name")],
        "budget_min": budget.get("minimum"),
        "budget_max": budget.get("maximum"),
        "currency": currency.get("code"),
        "usd_rate": currency.get("exchange_rate"),
        # Pais de la moneda, no del cliente: la API publica no expone el pais del cliente.
        "currency_country": currency.get("country"),
        "project_type": TYPES.get(raw.get("type")),
        "posted_at": datetime.fromtimestamp(submitted, timezone.utc) if submitted else None,
        "bid_count": (raw.get("bid_stats") or {}).get("bid_count"),
        "status": raw.get("status"),
        "language": raw.get("language"),
        "nonpublic": bool(raw.get("nonpublic")),
        "deleted": bool(raw.get("deleted")),
    }


def missing_required(project: dict) -> list[str]:
    return [f for f in REQUIRED_FIELDS if project.get(f) is None]


def passes_criteria(project: dict, criteria: dict, now: datetime) -> bool:
    """Filtro de busqueda; la relevancia fina corresponde al clasificador (fase 1)."""
    if project["nonpublic"] or project["deleted"]:
        return False
    text = f"{project['title']} {project['description'] or ''}".lower()
    if any(word.lower() in text for word in criteria.get("exclude_keywords", [])):
        return False
    languages = criteria.get("languages")
    if languages and project["language"] and project["language"] not in languages:
        return False
    if criteria.get("max_age_days") is not None:
        if project["posted_at"] < now - timedelta(days=criteria["max_age_days"]):
            return False
    minimum = criteria.get("min_budget_usd")
    if minimum is not None and project["usd_rate"]:
        top = project["budget_max"] if project["budget_max"] is not None else project["budget_min"]
        if top * project["usd_rate"] < minimum:
            return False
    return True
