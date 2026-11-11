# 001 · Registro de fuentes y criterios

Requisitos del PRD en formato EARS.

- **RF-FUE-01:** El sistema debe mantener un registro de fuentes con nombre, URL base, modo de acceso (API, feed, email, scraping, manual), estado legal (permitido, pendiente, prohibido), frecuencia y límite de tasa.
- **RF-FUE-02:** El sistema debe permitir definir búsquedas por fuente: categorías, palabras incluidas y excluidas, idiomas, presupuesto mínimo y antigüedad máxima.
- **RF-FUE-03:** Si el estado legal de una fuente no es «permitido», entonces el sistema no debe ejecutar su conector automático.
- **RF-FUE-04:** El sistema debe versionar los criterios y registrar en cada corrida qué versión usó.

## Criterios de aceptación

- Con una fuente `pendiente`, `prohibido` o inactiva, la ingesta termina sin peticiones de red y sin crear corrida.
- Cambiar los criterios crea una versión nueva; sincronizar sin cambios no crea ninguna.
- Cada corrida referencia el perfil exacto que usó.
