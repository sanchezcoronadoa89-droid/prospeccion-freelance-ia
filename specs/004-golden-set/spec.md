# 004 · Golden set

Muestra fija de hasta 200 proyectos para medir el pipeline. Es el último requisito para cerrar la fase 0.

## Requisitos

- La muestra debe incluir negativos difíciles y publicaciones en español, portugués e inglés, con división fija en desarrollo y test (70/30).
- Cuando una persona etiqueta, el sistema no debe mostrarle respuestas anteriores ni el acuerdo hasta terminar las dos sesiones comparadas.
- Si la misma persona repite la muestra, el sistema debe abrir la segunda pasada al menos 7 días después y en otro orden.
- El sistema debe calcular kappa de categoría y relevancia, y kappa con pesos cuadráticos de complejidad y calidad. Se pasa con al menos 0,6 en los cuatro.

## Desviaciones del PRD

- **Alcance y perfil (6 nov 2026).** El PRD se centra en UX/UI y SEO para un equipo. Por decisión del titular, el perfil es una persona especializada en marketing digital y analítica, con experiencia en UX/UI, programación junior e IA avanzada. Las categorías pasan a `marketing`, `seo`, `ia_automatizacion`, `web_simple`, `ux_ui` y `otra` (sin «ambas»), y `relevante` significa que esa persona podría entregarlo.
- **Complejidad.** Campo nuevo (baja, media, alta) para el eje de esfuerzo de la matriz esfuerzo-rentabilidad.
- **Dos pasadas en lugar de dos personas.** El titular del proyecto etiqueta solo (6 nov 2026). Mide la coherencia de una persona, no el acuerdo entre dos: es un criterio más débil, porque no detecta sesgos propios. Si se suma otra persona, el flujo compara a ambas sin más cambios.
- **Complejidad y calidad con pesos cuadráticos.** El PRD no indica el tipo de kappa. Son escalas ordenadas, y el kappa simple trataría un 4 frente a un 5 igual que un 1 frente a un 5.
- **Sin señales del cliente en la calidad.** El conector aún no las obtiene.

## Pendiente

La exactitud de los campos extraídos se etiqueta aparte, desde la auditoría, y los fixtures del eval de extracción se generan en la fase 1.
