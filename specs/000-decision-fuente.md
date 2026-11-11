# 000 · Decisión de la fuente inicial

**Estado: resuelta el 6 nov 2026.** `freelancer` está en `permitido` por decisión del titular del proyecto, que declara tener permiso de Freelancer para el acceso automatizado y para conservar datos más de 24 horas.

**Pendiente:** adjuntar aquí el permiso. Su texto no se ha revisado, así que su alcance y condiciones constan solo por esa declaración.

Revisión técnica de los términos del 5 nov 2026; no es asesoramiento legal.

## Decisión tomada

La fase 1 usará la API de Freelancer.com. Más adelante se construirá un scraper, sujeto a las mismas reglas: necesita una fuente con estado `permitido` (RF-FUE-03) y no evade bloqueos (RF-ING-03).

## Qué dicen los términos

**[API Terms and Conditions](https://www.freelancer.com/about/apiterms)** (última modificación: 21 dic 2017)

- Sección 3: concede una licencia limitada para usar la API e integrarla en productos o servicios.
- Sección 4: prohíbe replicar o competir con los servicios de Freelancer, y superar los límites de uso. También indica: «You will not rely on the functioning or correct function of the API in the conduct of your ordinary course business».
- Sección 5: «This limited permission to cache is for performance reasons only», con refresco al menos cada 24 horas. También: «You may not copy or store any Data [...] except to the extent permitted by these API T&Cs». Los datos almacenados deben usar cifrado fuerte.
- Sección 7: al terminar el acuerdo hay que borrar los datos almacenados, salvo pacto escrito.

**[User Agreement](https://www.freelancer.com/about/terms)**, cláusula 33: «You agree that you will not use any robot, spider, scraper or other automated means to access the Website via any means, including for the avoidance of doubt access to our API or application programming interface, for any purpose without our express written permission».

## Por qué bloquea

| Necesidad del PRD | Conflicto |
|---|---|
| `raw_snapshots`, para re-extraer sin volver a la fuente | Almacenamiento más allá de la caché de 24 h |
| `project_versions` y `market_metrics`, histórico propio | Conservar y derivar datos a largo plazo |
| Golden set con fixtures de proyectos reales | Conservar datos indefinidamente |
| Corridas automáticas por cron | La cláusula 33 pide permiso escrito para acceso automatizado |

La licencia de la sección 3 y la cláusula 33 pueden leerse en tensión. Hay que aclararlo con Freelancer, no interpretarlo a favor nuestro.

## Opciones

1. **Pedir permiso escrito a Freelancer (recomendada).** Describir el uso interno: consulta automatizada, retención del histórico y sus plazos. Contacto publicado en los términos: support@freelancer.com.
2. **Modo sin histórico.** Exige que el permiso cubra el acceso automatizado y borrar los datos a las 24 h. Elimina snapshots, histórico, tendencias y fixtures reales: requiere cambiar el PRD.
3. **Otra fuente** con términos compatibles, evaluada con este mismo documento.

## Cómo se cierra

Una persona adjunta aquí el permiso o la decisión, cambia `legal_status` en `config/sources.yaml` y registra fecha y responsable. Si es posible, conviene validarlo con un abogado, como recomienda el PRD.

## Registro de accesos

- 5 nov 2026: durante el análisis se hicieron dos consultas anónimas a la API (`limit=1`) para comprobar su disponibilidad, antes de leer estas cláusulas. La respuesta no se guardó. No ha habido más accesos a la API.
- 6 nov 2026: primera ingesta real con la fuente en `permitido` (corrida #1: 25 páginas, 436 proyectos).
