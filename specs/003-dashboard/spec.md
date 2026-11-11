# 003 · Dashboard de validación

Implementado con FastAPI y React en lugar de Streamlit, por decisión del titular del proyecto (6 nov 2026).

- **RF-DSH-01:** Cuando una persona marca un campo como incorrecto en la auditoría, el sistema debe guardar el valor correcto en `labels`.
- **RF-DSH-02:** El dashboard debe mostrar para cada número la corrida y la versión de prompt o rúbrica que lo produjo.
- **RF-DSH-03:** El dashboard debe ser de solo lectura sobre los datos de ingesta; solo escribe etiquetas y correcciones.

Vistas de fase 1: salud de ingesta, auditoría de extracción, bandeja de proyectos, calidad del filtro, fuentes y costos.

Solo escucha en `127.0.0.1` y no tiene autenticación: el multiusuario está fuera del alcance del PRD.
