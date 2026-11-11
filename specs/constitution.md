# Constitución del proyecto

Reglas que ninguna spec puede saltarse. Fuente: PRD del pipeline de prospección.

1. **Acceso legítimo.** Ninguna fuente se ejecuta sin estado `permitido`. No se evaden CAPTCHA ni bloqueos, y solo una persona cambia el estado legal.
2. **Sin datos personales.** No se guardan nombres, usuarios ni contactos de quienes publican.
3. **Sin acciones en nombre de la cuenta.** Nada envía propuestas o mensajes, inicia sesión ni guarda credenciales de usuario. Si una API exige token, se decide explícitamente en `specs/000-decision-fuente.md`.
4. **Código para calcular, LLM para interpretar.** Todo cálculo numérico se hace en código.
5. **Medir antes de depender.** Cada etapa tiene su eval antes de que otra dependa de ella. Las fases avanzan por criterios de salida, no por fechas.
6. **Trazabilidad.** Todo resultado guarda corrida, modelo y versión de prompt o rúbrica. Prompts, rúbricas y criterios se versionan en git.
7. **Decisión humana antes de producir.** Solo los proyectos elegidos por una persona pasan a propuesta, contenido y web.
