---
description: Clasifica proyectos con reglas y, en los casos dudosos, con el agente clasificador
argument-hint: "[corrida] [--limit N] [--include-golden]"
allowed-tools: Bash(.venv/Scripts/python -m scripts.classify:*)
---

Ejecuta exactamente `.venv/Scripts/python -m scripts.classify $ARGUMENTS` y resume el JSON de salida en pocas líneas: proyectos decididos por reglas, enviados al LLM, fallidos y costo.

Si `stopped_by_budget` es `true`, informa de que se alcanzó el tope de gasto de `config/pipeline.yaml`. No lo cambies sin que te lo pidan.

Usa `--include-golden` solo si te lo piden: esos proyectos se reservan hasta terminar de etiquetarlos.
