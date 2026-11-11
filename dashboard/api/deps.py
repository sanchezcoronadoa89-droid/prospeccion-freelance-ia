"""Dependencias compartidas de la API."""
from collections.abc import Iterator
from typing import Annotated
from urllib.parse import urlparse

import psycopg
from fastapi import Depends, HTTPException, Request

from scripts.db import connect

LOCAL_HOSTS = {"localhost", "127.0.0.1"}


def read_conn() -> Iterator[psycopg.Connection]:
    """Conexion de lectura: Postgres rechaza cualquier escritura en ella."""
    with connect() as conn:
        conn.read_only = True
        yield conn


def write_conn() -> Iterator[psycopg.Connection]:
    with connect() as conn:
        yield conn


Reader = Annotated[psycopg.Connection, Depends(read_conn)]
Writer = Annotated[psycopg.Connection, Depends(write_conn)]


def require_local_origin(request: Request) -> None:
    """Evita que una web externa envie etiquetas desde el navegador."""
    origin = request.headers.get("origin")
    if origin and urlparse(origin).hostname not in LOCAL_HOSTS:
        raise HTTPException(403, "Origen no permitido")
