"""Conexion a Postgres y aplicacion de migraciones SQL."""
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "migrations"


def connect(url: str | None = None) -> psycopg.Connection:
    load_dotenv(ROOT / ".env")
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Falta DATABASE_URL (ver .env.example)")
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)


class AlreadyRunning(RuntimeError):
    """Otra ejecucion del pipeline tiene el bloqueo."""


@contextmanager
def pipeline_lock(conn: psycopg.Connection, name: str = "pipeline"):
    """Impide dos ingestas, clasificaciones o ratings a la vez (bloqueo de sesion de Postgres)."""
    got = conn.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS ok", (name,)).fetchone()["ok"]
    conn.commit()
    if not got:
        raise AlreadyRunning("Ya hay una ejecución del pipeline en curso; espera a que termine.")
    try:
        yield
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (name,))
        conn.commit()


def migrate(conn: psycopg.Connection) -> list[str]:
    """Aplica en orden las migraciones pendientes y devuelve las aplicadas."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name not in done:
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
    conn.commit()
    return applied


if __name__ == "__main__":
    with connect() as c:
        print("Migraciones aplicadas:", migrate(c) or "ninguna")
