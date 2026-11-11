# Pipeline de prospección de proyectos

Fase 0, conector de ingesta y dashboard de validación. Decisión sobre la fuente en `specs/000-decision-fuente.md`.

## Arranque diario

Tras encender el PC, ejecuta `.\iniciar.ps1` (o clic derecho > Ejecutar con PowerShell). Abre Docker, levanta Postgres, arranca el dashboard en su propia ventana y abre http://localhost:8000. Cierra esa ventana para apagar el dashboard.

## Puesta en marcha

Requiere Python 3.12 o superior, Node 20 o superior y Docker.

```
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
cp .env.example .env        # y define tu contraseña
docker compose up -d        # o tu propio Postgres en el puerto 5433
.venv/Scripts/python -m scripts.db
.venv/Scripts/python -m pytest
```

## Uso

```
.venv/Scripts/python -m scripts.ingest freelancer
npm --prefix dashboard/web install
npm --prefix dashboard/web run build
.venv/Scripts/python -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8000
```

- Dashboard: http://localhost:8000
- Documentación de la API: http://localhost:8000/docs

Para desarrollar el frontend: `npm --prefix dashboard/web run dev` (http://localhost:5173), con la API en marcha.

Los tests no acceden a la red. Los de integración se omiten si `TEST_DATABASE_URL` no responde.

## Estructura

| Ruta | Contenido |
|---|---|
| `config/` | Fuentes y perfiles de búsqueda |
| `migrations/` | Esquema de Postgres |
| `scripts/` | Registro, conector, parser e ingesta |
| `dashboard/` | API en FastAPI y frontend en React |
| `config/presupuesto.yaml` | Tarifa, comisión y tabla de horas del presupuestador (valores de ejemplo: calíbralos) |
| `evals/` | Golden set y cálculo de kappa |
| `specs/` | Constitución, decisión de fuente y specs por módulo |
| `.claude/` | Comandos y, más adelante, agentes y skills |
