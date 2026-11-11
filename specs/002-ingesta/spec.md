# 002 · Ingesta

Requisitos del PRD en formato EARS.

- **RF-ING-01:** Cuando se ejecuta la ingesta de una fuente, el sistema debe obtener los listados, guardar el snapshot crudo y registrar la corrida: inicio, fin, páginas, ítems y errores.
- **RF-ING-02:** El conector debe respetar robots.txt, los términos de la fuente y el límite de tasa configurado.
- **RF-ING-03:** Si la fuente responde con CAPTCHA o bloqueo anti-bot, entonces el conector debe detenerse, marcar la corrida como bloqueada y no intentar evadirlo.
- **RF-ING-04:** El sistema debe extraer los campos estructurados con parsers deterministas; el LLM solo completa campos de texto libre.
- **RF-ING-05:** Si en una corrida más del 10 % de los ítems llega sin un campo obligatorio, entonces el sistema debe marcar «cambio de estructura» y no pasar esa corrida al análisis.
- **RF-ING-06:** El sistema debe deduplicar por fuente + id externo y marcar casi-duplicados entre fuentes por similitud de título y descripción.
- **RF-ING-07:** Cuando un proyecto ya guardado cambia de presupuesto, cantidad de propuestas o estado, el sistema debe guardar una nueva versión, no sobrescribir.

## Decisiones de interpretación

- Un 10 % exacto no es cambio de estructura («más del 10 %»): la corrida queda `parcial`.
- Una respuesta 401, 403, 429 o 503, o no JSON con estado correcto, se trata como bloqueo y no se reintenta.
- En una corrida bloqueada o con cambio de estructura no se guardan proyectos; los snapshots sí, para poder re-extraer.
- Los snapshots se filtran antes de escribirse: el dato personal no llega al disco.
