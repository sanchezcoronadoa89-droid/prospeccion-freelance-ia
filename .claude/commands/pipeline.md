---
description: Ejecuta ingesta, clasificación y rating de una fuente en una sola orden
argument-hint: "<fuente> [--full]"
allowed-tools: Bash(.venv/Scripts/python -m scripts.pipeline:*)
---

Ejecuta exactamente `.venv/Scripts/python -m scripts.pipeline $ARGUMENTS` y resume el JSON en pocas líneas: modo de la ingesta (completa o incremental), proyectos nuevos, cobertura, proyectos clasificados y puntuados, y costo.

- `detenida`: la ingesta no quedó en `ok` ni `parcial`; explica por qué y no lances los agentes por separado.
- `tope_de_gasto`: se alcanzó el tope de `config/pipeline.yaml`. No lo cambies sin que te lo pidan.
- `no_ejecutada`: la fuente no está en `permitido`. No cambies `legal_status`.

Usa `--full` solo si te lo piden o si hace más de una semana de la última corrida completa: es la única forma de refrescar propuestas y estados de proyectos antiguos.
