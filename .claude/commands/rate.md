---
description: Puntúa la calidad de los proyectos relevantes y recalcula el rating de las fuentes
argument-hint: "[corrida] [--limit N] [--include-golden]"
allowed-tools: Bash(.venv/Scripts/python -m scripts.rate:*)
---

Ejecuta exactamente `.venv/Scripts/python -m scripts.rate $ARGUMENTS` y resume el JSON de salida en pocas líneas: proyectos puntuados, fallidos, fuentes y costo.

Si `stopped_by_budget` es `true`, informa de que se alcanzó el tope de gasto de `config/pipeline.yaml`. No lo cambies sin que te lo pidan.
