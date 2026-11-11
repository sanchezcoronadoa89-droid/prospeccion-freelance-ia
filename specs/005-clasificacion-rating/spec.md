# 005 · Clasificación y rating (fase 1)

Requisitos del PRD: RF-CLA-01 a 03 y RF-RAT-01 a 03. Categorías y perfil según `specs/004-golden-set/spec.md`.

## Decisiones

- **Fase abierta sin el criterio de salida.** El 6 nov 2026 el titular del proyecto pidió avanzar antes de completar el golden set. Los agentes funcionan, pero **su calidad no está medida** hasta tener kappa ≥ 0,6 y ejecutar `/eval`. Sus resultados son orientativos.
- **Golden set reservado.** Sus proyectos no se clasifican ni puntúan hasta terminar de etiquetarlos, para no influir en las etiquetas. Después se ejecuta con `--include-golden`.
- **Agentes como procesos aislados.** `scripts/agent_runner.py` lanza `claude -p` con la definición de `.claude/agents/`, sin herramientas, sin MCP y fuera del proyecto. El agente solo devuelve JSON; el código valida, guarda y registra el costo. Es más estricto que el subagente del PRD y evita acumular proyectos en el contexto. La definición en prosa sigue siendo migrable a LangGraph.
- **El LLM no calcula.** El agente puntúa criterios y el código calcula la nota, con los pesos de `config/rubrica_calidad_v1.yaml`.
- **Reglas conservadoras.** Solo deciden `otra` cuando no hay ninguna señal. Lo demás va al LLM, para no perder recall.
- **Reutilización.** No se repite una llamada si no cambian el contenido ni el prompt.
- **Costos.** `cost_usd` es lo que informa la CLI a precio de lista; con una suscripción, el gasto real puede ser distinto. Se imputa a la última corrida de ingesta válida.

## Pendiente

- Medir con `/eval classify` y `/eval rate` tras etiquetar; hasta entonces los umbrales del PRD no están comprobados.
- Señales del cliente en la rúbrica, cuando el conector las obtenga.
