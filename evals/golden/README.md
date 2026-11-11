# Golden set

Muestra de hasta 200 proyectos etiquetados a mano, que sirve de «respuesta correcta» para medir el pipeline. La muestra es `sample_v2.json`, los criterios `rubrica_v2.md` (la v1 queda como historial, sin etiquetas) y las reglas `specs/004-golden-set/spec.md`. Se etiqueta en la pestaña **Golden set** del dashboard.

## Cómo se etiqueta

La misma persona etiqueta la muestra dos veces, con al menos 7 días entre pasadas y sin ver sus respuestas anteriores: categoría, relevancia, complejidad y calidad de 1 a 5. Si participa otra persona, se comparan las dos. Debe incluir negativos difíciles (un desarrollo que menciona SEO, un logo que menciona UX) y posts en español, portugués e inglés, con división fija en `dev` y `test`.

## Medir el acuerdo

Kappa de Cohen mide cuánto coinciden dos sesiones de etiquetado descontando las coincidencias que se darían por azar. Va de 1 (acuerdo total) a 0 (lo esperable por azar). El PRD exige al menos 0,6; por debajo, la rúbrica está mal definida y hay que aclararla.

```
.venv/Scripts/python -m evals.kappa etiquetas.csv persona_a persona_b
```
