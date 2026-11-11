# Pipeline de prospección de proyectos

Detecta proyectos de marketing digital, analítica, SEO, IA y automatización, web simple y UX/UI en plataformas freelance, los puntúa y estima su rentabilidad. El perfil es de una persona; las desviaciones del PRD están en `specs/004-golden-set/spec.md`. Requisitos en `PRD.pdf`; reglas innegociables en `specs/constitution.md`.

## Estado

Fase 0 en curso. `freelancer` está en `permitido` desde el 6 nov 2026 (`specs/000-decision-fuente.md`). Falta el golden set para cerrar la fase: se etiqueta en dos pasadas (`specs/004-golden-set/spec.md`), pero el titular pidió adelantar la fase 1: los agentes funcionan sin estar medidos (`specs/005-clasificacion-rating/spec.md`).

## Reglas

- Nunca cambies `legal_status` en `config/sources.yaml` por tu cuenta: es una decisión humana.
- No accedas a una fuente que no esté en `permitido`, ni siquiera para probar. Los tests usan HTTP simulado.
- No evadas CAPTCHA ni bloqueos, y no guardes nombres, usuarios ni contactos de quienes publican.
- Todo cálculo numérico va en código; el LLM solo interpreta texto y redacta.
- Avanza de fase solo cuando se cumpla el criterio de salida del PRD.

## Pipeline

`/pipeline <fuente>` encadena `/ingest <fuente>` (sin LLM, incremental por defecto) → `/classify` → `/rate`; después, `/eval <etapa>`. La ingesta busca por skills oficiales y mide su cobertura (`specs/006-flujo-ingesta/spec.md`). Los agentes están en prosa en `.claude/agents/` y los ejecuta `scripts/agent_runner.py` como procesos aislados sin herramientas: devuelven JSON y el código lo valida y guarda. Se pasan datos por la base, no por el contexto.

## Comandos

```
.venv/Scripts/python -m pytest          # tests
.venv/Scripts/python -m scripts.db      # migraciones
.venv/Scripts/python -m scripts.pipeline <fuente> [--full]
.venv/Scripts/python -m scripts.ingest <fuente> [--full]
.venv/Scripts/python -m scripts.classify [corrida] [--limit N]
.venv/Scripts/python -m scripts.rate [corrida] [--limit N]
.venv/Scripts/python -m evals.run classify|rate
.venv/Scripts/python -m scripts.budget <project_id>   # presupuesto y borrador, sin enviar
.venv/Scripts/python -m evals.kappa <csv> <col_a> <col_b>
.venv/Scripts/python -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8000   # dashboard
npm --prefix dashboard/web run build    # recompila el frontend
```

## Dashboard

FastAPI y React, en lugar del Streamlit del PRD, por decisión del titular del proyecto. Las lecturas usan conexiones `read_only`. Escribe etiquetas y, a petición del titular, lanza el pipeline y genera presupuestos (`dashboard/api/actions.py`, `specs/007-acciones-y-presupuesto/spec.md`).

## Convenciones

Cada módulo tiene su carpeta numerada en `specs/` (spec EARS, plan y tasks). Los cambios de esquema van en un archivo nuevo de `migrations/`. Una fuente nueva añade su conector en `scripts/connectors/`, su parser en `scripts/parsers/` y su entrada en `CONNECTORS`.
