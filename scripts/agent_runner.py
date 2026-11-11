"""Ejecuta agentes en prosa como procesos aislados de Claude Code, sin herramientas.

El agente solo recibe datos y devuelve JSON. El codigo valida, guarda, reintenta,
registra el costo en agent_calls y aplica el tope de gasto.
"""
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from scripts.db import ROOT

AGENTS_DIR = ROOT / ".claude" / "agents"
PIPELINE_PATH = ROOT / "config" / "pipeline.yaml"
CALL_TIMEOUT_SECONDS = 300


@dataclass
class AgentSpec:
    name: str
    model: str
    version: str
    system_prompt: str

    @property
    def prompt_version(self) -> str:
        digest = hashlib.sha256(self.system_prompt.encode("utf-8")).hexdigest()[:8]
        return f"{self.name}-v{self.version}-{digest}"


@dataclass
class AgentReply:
    ok: bool
    text: str = ""
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None


def load_pipeline_config(path=PIPELINE_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_agent(name: str, agents_dir=AGENTS_DIR) -> AgentSpec:
    text = Path(agents_dir, f"{name}.md").read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front)
    return AgentSpec(meta["name"], meta["model"], str(meta["version"]), body.strip())


def content_hash(*parts) -> str:
    canonical = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_cli_output(stdout: str, latency_ms: int) -> AgentReply:
    try:
        data = json.loads(stdout)
    except ValueError:
        return AgentReply(ok=False, latency_ms=latency_ms, error="Salida de la CLI no es JSON")
    usage = data.get("modelUsage") or {}
    reply = AgentReply(
        ok=not data.get("is_error") and data.get("subtype", "success") == "success",
        text=data.get("result") or "",
        # La CLI puede usar un modelo pequeno para tareas internas: el que hizo el trabajo es el de mayor coste.
        model=max(usage, key=lambda name: (usage[name].get("costUSD", 0), usage[name].get("outputTokens", 0)),
                  default=None),
        input_tokens=sum(u.get("inputTokens", 0) + u.get("cacheReadInputTokens", 0)
                         + u.get("cacheCreationInputTokens", 0) for u in usage.values()),
        output_tokens=sum(u.get("outputTokens", 0) for u in usage.values()),
        cost_usd=float(data.get("total_cost_usd") or 0),
        latency_ms=latency_ms,
    )
    if not reply.ok:
        reply.error = str(data.get("result") or data.get("subtype") or "Error de la CLI")[:300]
    return reply


def call_claude(spec: AgentSpec, payload: str) -> AgentReply:
    """Llama al modelo sin herramientas, sin MCP y fuera del proyecto."""
    executable = shutil.which("claude")
    if executable is None:
        return AgentReply(ok=False, error="No se encontro la CLI de Claude Code")
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as workdir:
        prompt_file = Path(workdir, "system.md")
        prompt_file.write_text(spec.system_prompt, encoding="utf-8")
        try:
            result = subprocess.run(
                [executable, "-p", "--model", spec.model, "--output-format", "json", "--tools", "",
                 "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "",
                 "--system-prompt-file", str(prompt_file)],
                input=payload, capture_output=True, text=True, encoding="utf-8", errors="replace",
                cwd=workdir, timeout=CALL_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return AgentReply(ok=False, latency_ms=CALL_TIMEOUT_SECONDS * 1000, error="Tiempo agotado")
    latency = int((time.monotonic() - started) * 1000)
    if result.returncode != 0 and not result.stdout.strip():
        return AgentReply(ok=False, latency_ms=latency, error=result.stderr.strip()[:300] or "Error de la CLI")
    return parse_cli_output(result.stdout, latency)


def parse_items(text: str) -> list[dict] | None:
    """Extrae la lista items de la respuesta; None si no es JSON valido."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else None


def _log_call(conn, run_id, spec: AgentSpec, reply: AgentReply, result: str) -> None:
    conn.execute(
        """INSERT INTO agent_calls (run_id, agent, model, prompt_version, input_tokens, output_tokens,
               cost_usd, latency_ms, result) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (run_id, spec.name, reply.model or spec.model, spec.prompt_version, reply.input_tokens,
         reply.output_tokens, reply.cost_usd, reply.latency_ms, result),
    )
    conn.execute("UPDATE runs SET cost_usd = cost_usd + %s WHERE id = %s", (reply.cost_usd, run_id))


def process_in_batches(conn, spec: AgentSpec, projects: list[dict], *, run_id: int,
                       build_item: Callable[[dict], dict], validate: Callable[[dict], dict | None],
                       save: Callable[[dict, dict, str | None], None], give_up: Callable[[dict], None],
                       batch_size: int, max_cost_usd: float, runner=call_claude) -> dict:
    """Procesa por lotes. Lo invalido se reintenta una vez y despues pasa a give_up (RF-CLA-03)."""
    stats = {"processed": 0, "failed": 0, "calls": 0, "cost_usd": 0.0, "stopped_by_budget": False}
    for start in range(0, len(projects), batch_size):
        if stats["cost_usd"] >= max_cost_usd:
            stats["stopped_by_budget"] = True
            break
        pending = {p["id"]: p for p in projects[start:start + batch_size]}
        for attempt in (1, 2):
            payload = json.dumps({"items": [build_item(p) for p in pending.values()]}, ensure_ascii=False)
            reply = runner(spec, payload)
            items = parse_items(reply.text) if reply.ok else None
            stats["calls"] += 1
            stats["cost_usd"] += reply.cost_usd
            valid = 0
            for raw in items or []:
                project = pending.get(raw.get("id")) if isinstance(raw, dict) else None
                cleaned = validate(raw) if project else None
                if cleaned is not None:
                    save(project, cleaned, reply.model)
                    del pending[project["id"]]
                    valid += 1
            stats["processed"] += valid
            if not reply.ok:
                result = "error"
            else:
                result = "ok" if not pending else "schema_error"
            _log_call(conn, run_id, spec, reply, result)
            conn.commit()
            if not pending or attempt == 2 or stats["cost_usd"] >= max_cost_usd:
                break
        for project in pending.values():
            give_up(project)
        stats["failed"] += len(pending)
        conn.commit()
    return stats
