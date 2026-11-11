# 007 · Acciones en el dashboard y presupuestador

Pedido por el titular el 11 nov 2026. Adelanta parte de las fases 2 y 3 del PRD.

## Requisitos

- **RF-DSH-04:** El dashboard debe ofrecer un acceso visible a la publicación original desde la bandeja y desde el detalle.
- **RF-DSH-05:** Cuando una persona pulsa «Ejecutar ingesta ahora», el sistema debe lanzar `scripts.pipeline` de la fuente indicada. Si ya hay una ejecución en curso, o la fuente no está en `permitido`, no debe lanzar nada y debe decir por qué.
- **RF-DSH-06:** La cabecera debe mostrar siempre un botón «Actualizar» que lanza el pipeline incremental, cuándo fue la última actualización y cada cuánto se actualiza sola. La frecuencia sale de `auto_update_every_hours` en `config/pipeline.yaml`; mientras sea `null`, el dashboard debe decir que no hay búsqueda automática programada.
- **RF-ING-08:** Cuando una corrida queda en `en_curso` sin que nadie tenga el bloqueo del pipeline, el dashboard debe mostrarla como `interrumpida`, y la siguiente ingesta debe cerrarla así en la base (migración 007).
- **RF-PRO-02:** Para un proyecto elegido, el sistema debe generar un presupuesto en tres escenarios y un borrador de propuesta. Nunca debe enviarlo.
- **RF-REN-05:** Horas, coste, precio, margen y plazo se calculan en código con `config/presupuesto.yaml`. La IA solo identifica tareas y unidades, y redacta usando las cifras calculadas.
- **RF-INV-03:** Las fuentes candidatas se registran en `pendiente` y desactivadas hasta que una persona revise sus términos.

## Cómo funciona el presupuesto

1. El agente `presupuestador` (Sonnet) lee la publicación y devuelve tareas del catálogo, unidades, la frase que lo justifica, preguntas, información que falta y señales de riesgo.
2. El código suma `unidades × horas` por escenario, multiplica por la tarifa y divide por `1 − comisión` para obtener el precio. El margen se calcula frente al presupuesto máximo del cliente, descontada la comisión. El precio recomendado es el del escenario medio, redondeado hacia arriba a múltiplos de 5 USD.
3. El agente `redactor-propuestas` (Sonnet) escribe el borrador en el idioma de la publicación con ese precio y ese plazo. Si el borrador no menciona el precio calculado, se avisa.
4. Se guarda en `proposals` y en `profitability`. Cada llamada queda en `agent_calls`.

## Desviaciones del PRD

- **Dashboard que actúa:** RF-DSH-03 pedía un dashboard de solo lectura sobre la ingesta. Ahora lanza el pipeline (que escribe por su cuenta, protegido por el bloqueo) y guarda presupuestos.
- **Tabla nueva `proposals`:** el esquema pasa de 13 a 14 tablas.
- **Fases adelantadas:** el criterio de salida de las fases 1 y 2 no se ha cumplido; el presupuesto no está medido.

## Pendiente

- **Búsqueda automática:** programarla en el Programador de tareas de Windows necesita autorización del titular y confirmar que el permiso de Freelancer cubre el acceso automatizado (`specs/000-decision-fuente.md`). Al hacerlo, poner sus horas en `auto_update_every_hours`.

- **Calibrar `config/presupuesto.yaml`:** tarifa, comisión real y horas. Mientras `calibrated` sea `false`, cada presupuesto lo avisa.
- Backtest de horas estimadas frente a reales en proyectos ganados (eval de rentabilidad del PRD).
- Revisar los términos de upwork, peopleperhour, guru y malt antes de pensar en conectores.
