"""Conector de la API publica de Freelancer.com. Sin credenciales ni evasion.

Busca por skills oficiales (jobs[]) y por palabras clave. Varias skills en una misma
peticion se combinan con O. Con `since`, solo pide proyectos publicados desde esa fecha.
"""
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from urllib.robotparser import RobotFileParser

import httpx

API_PATH = "/api/projects/0.1/projects/active/"
JOBS_PATH = "/api/projects/0.1/jobs/"
USER_AGENT = "prospeccion-pipeline/0.1"
BLOCK_STATUS = {401, 403, 429, 503}
JOBS_PER_QUERY = 8
# Lista blanca: lo que no aparece aqui (owner_id, users...) nunca llega al disco.
PROJECT_FIELDS = {
    "id", "title", "status", "seo_url", "currency", "description", "preview_description",
    "jobs", "submitdate", "type", "budget", "hourly_project_info", "bid_stats", "language",
    "deleted", "nonpublic",
}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{7,}\d(?![\w])")


class BlockedError(Exception):
    """CAPTCHA, bloqueo o limite de la fuente: se detiene, no se reintenta (RF-ING-03)."""


class FetchError(Exception):
    """Error de la fuente que no indica bloqueo."""


@dataclass
class Page:
    url: str
    payload: dict
    query: str = ""
    total_count: int | None = None


def redact(text):
    if not isinstance(text, str):
        return text
    return PHONE_RE.sub("[contacto eliminado]", EMAIL_RE.sub("[contacto eliminado]", text))


def sanitize_payload(payload: dict) -> dict:
    """Quita datos personales antes de escribir el snapshot."""
    projects = []
    for raw in (payload.get("result") or {}).get("projects") or []:
        clean = {k: v for k, v in raw.items() if k in PROJECT_FIELDS}
        for key in ("title", "description", "preview_description"):
            clean[key] = redact(clean.get(key))
        projects.append(clean)
    return {"status": payload.get("status"), "result": {"projects": projects}}


class FreelancerConnector:
    def __init__(self, base_url: str, rate_limit_per_min: int, client: httpx.Client,
                 sleep: Callable[[float], None] = time.sleep):
        self.base_url = base_url.rstrip("/")
        self.interval = 60.0 / rate_limit_per_min
        self.client = client
        self.sleep = sleep
        self._used = False
        self.warnings: list[str] = []

    def _get(self, url: str, params=None) -> httpx.Response:
        if self._used:
            self.sleep(self.interval)
        self._used = True
        try:
            return self.client.get(url, params=params, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as exc:
            raise FetchError(f"Error de red: {exc}") from exc

    def _check_robots(self) -> None:
        response = self._get(f"{self.base_url}/robots.txt")
        if response.status_code in BLOCK_STATUS:
            raise BlockedError(f"robots.txt respondio {response.status_code}")
        if response.status_code >= 400:
            return  # Sin robots.txt publicado no hay reglas que aplicar.
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        if not parser.can_fetch(USER_AGENT, self.base_url + API_PATH):
            raise BlockedError("robots.txt no permite acceder a la API")

    def resolve_job_ids(self, names: list[str]) -> list[int]:
        """Traduce nombres de skills a IDs con la taxonomia oficial; avisa de los que no existen."""
        payload = self._decode(self._get(self.base_url + JOBS_PATH))
        jobs = payload["result"] if isinstance(payload["result"], list) else []
        index = {(job.get("name") or "").strip().lower(): job["id"] for job in jobs if "id" in job}
        ids = []
        for name in names:
            job_id = index.get(name.strip().lower())
            if job_id is None:
                self.warnings.append(f"Skill desconocida en la API: {name}")
            else:
                ids.append(job_id)
        return ids

    def _queries(self, criteria: dict) -> list[tuple[str, list]]:
        queries = []
        if criteria.get("job_names"):
            ids = self.resolve_job_ids(criteria["job_names"])
            for start in range(0, len(ids), JOBS_PER_QUERY):
                chunk = ids[start:start + JOBS_PER_QUERY]
                queries.append((f"skills {start // JOBS_PER_QUERY + 1}", [("jobs[]", i) for i in chunk]))
        for keyword in criteria.get("include_keywords", []):
            queries.append((keyword, [("query", keyword)]))
        return queries

    def fetch_pages(self, criteria: dict, since: datetime | None = None) -> Iterator[Page]:
        self._check_robots()
        page_size, max_pages = criteria["page_size"], criteria["max_pages"]
        for label, query_params in self._queries(criteria):
            for page_number in range(max_pages):
                params = query_params + [("limit", page_size), ("offset", page_number * page_size),
                                         ("full_description", "true"), ("job_details", "true")]
                params += [("languages[]", lang) for lang in criteria.get("languages", [])]
                if since is not None:
                    params.append(("from_time", int(since.timestamp())))
                response = self._get(self.base_url + API_PATH, params)
                payload = self._decode(response)
                total = payload["result"].get("total_count")
                yield Page(str(response.url), sanitize_payload(payload), label,
                           total if isinstance(total, int) else None)
                if len(payload["result"].get("projects") or []) < page_size:
                    break

    @staticmethod
    def _decode(response: httpx.Response) -> dict:
        if response.status_code in BLOCK_STATUS:
            raise BlockedError(f"La fuente respondio {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            if response.status_code >= 400:
                raise FetchError(f"La fuente respondio {response.status_code}") from exc
            raise BlockedError("Respuesta no JSON: posible CAPTCHA o bloqueo anti-bot") from exc
        if response.status_code >= 400:
            raise FetchError(f"La fuente respondio {response.status_code}")
        if payload.get("status") != "success" or not isinstance(payload.get("result"), (dict, list)):
            raise FetchError(f"Respuesta inesperada: status={payload.get('status')!r}")
        return payload
