---
description: Evalúa una etapa contra el golden set y la última línea base
argument-hint: "classify|rate [--split dev|test]"
allowed-tools: Bash(.venv/Scripts/python -m evals.run:*)
---

Ejecuta exactamente `.venv/Scripts/python -m evals.run $ARGUMENTS` y resume métricas, umbrales y regresiones.

Si `n` es 0, explica que faltan etiquetas del golden set o resultados del agente. Nunca ajustes prompts usando la división `test`, solo `dev`. Una métrica que caiga más de 2 puntos no se adopta sin explicarla.
