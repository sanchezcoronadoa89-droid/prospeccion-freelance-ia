"""Registro de fuentes y perfiles de busqueda versionados (RF-FUE-01 a 04)."""
import hashlib
import json
from pathlib import Path

import yaml
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = ROOT / "config" / "sources.yaml"
PROFILES_PATH = ROOT / "config" / "search_profiles.yaml"
REQUIRED = ("name", "base_url", "access_mode", "legal_status", "rate_limit_per_min")


class SourceNotAllowed(Exception):
    """La fuente no puede ejecutarse automaticamente (RF-FUE-03)."""


def sync_registry(conn, sources_path=SOURCES_PATH, profiles_path=PROFILES_PATH) -> None:
    """Lleva a la base lo definido en config/, versionando criterios si cambiaron."""
    sources = yaml.safe_load(Path(sources_path).read_text(encoding="utf-8"))["sources"]
    profiles = yaml.safe_load(Path(profiles_path).read_text(encoding="utf-8"))["profiles"]
    for s in sources:
        missing = [k for k in REQUIRED if not s.get(k)]
        if missing:
            raise ValueError(f"Fuente {s.get('name')!r} sin campos: {missing}")
        row = conn.execute(
            """INSERT INTO sources (name, base_url, access_mode, legal_status, terms_url,
                   legal_notes, frequency, rate_limit_per_min, active)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (name) DO UPDATE SET base_url=EXCLUDED.base_url,
                   access_mode=EXCLUDED.access_mode, legal_status=EXCLUDED.legal_status,
                   terms_url=EXCLUDED.terms_url, legal_notes=EXCLUDED.legal_notes,
                   frequency=EXCLUDED.frequency, rate_limit_per_min=EXCLUDED.rate_limit_per_min,
                   active=EXCLUDED.active, updated_at=now()
               RETURNING id""",
            (s["name"], s["base_url"], s["access_mode"], s["legal_status"], s.get("terms_url"),
             s.get("legal_notes"), s.get("frequency"), s["rate_limit_per_min"],
             bool(s.get("active"))),
        ).fetchone()
        if s["name"] in profiles:
            _sync_profile(conn, row["id"], profiles[s["name"]])
    conn.commit()


def _sync_profile(conn, source_id: int, criteria: dict) -> None:
    canonical = json.dumps(criteria, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    current = conn.execute(
        "SELECT content_hash FROM search_profiles WHERE source_id=%s AND active", (source_id,)
    ).fetchone()
    if current and current["content_hash"] == digest:
        return
    conn.execute("UPDATE search_profiles SET active=FALSE WHERE source_id=%s AND active", (source_id,))
    conn.execute(
        """INSERT INTO search_profiles (source_id, version, criteria, content_hash)
           SELECT %s, COALESCE(MAX(version),0)+1, %s, %s FROM search_profiles WHERE source_id=%s""",
        (source_id, Jsonb(criteria), digest, source_id),
    )


def get_source(conn, name: str) -> dict:
    row = conn.execute("SELECT * FROM sources WHERE name=%s", (name,)).fetchone()
    if row is None:
        raise SourceNotAllowed(f"La fuente {name!r} no esta en el registro")
    return row


def assert_source_allowed(source: dict) -> None:
    """Puerta legal: se llama antes de cualquier acceso de red."""
    if source["legal_status"] != "permitido":
        raise SourceNotAllowed(
            f"{source['name']}: estado legal {source['legal_status']!r}; "
            "solo se ejecutan fuentes 'permitido' (RF-FUE-03)"
        )
    if not source["active"]:
        raise SourceNotAllowed(f"{source['name']}: la fuente no esta activa")


def get_active_profile(conn, source_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM search_profiles WHERE source_id=%s AND active", (source_id,)
    ).fetchone()
    if row is None:
        raise SourceNotAllowed("La fuente no tiene perfil de busqueda activo")
    return row
