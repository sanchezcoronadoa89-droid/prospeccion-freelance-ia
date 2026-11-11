# 006 · Flujo de ingesta v2 y filtros de mercado

Mejoras del 10 nov 2026 sobre `specs/002-ingesta`.

## Requisitos

- **RF-ING-08:** El sistema debe buscar por skills oficiales de la fuente, resueltas por nombre contra su taxonomía, y avisar de los nombres que no existan.
- **RF-ING-09:** Cuando existe una corrida válida con el mismo perfil, el sistema debe pedir solo lo publicado desde su inicio menos 2 horas. Si el perfil cambió, o se pide `--full`, la corrida es completa.
- **RF-ING-10:** El sistema debe guardar por búsqueda cuántos proyectos dice tener la fuente y cuántos se descargaron, y calcular la cobertura de captura.
- **RF-MER-04:** El sistema debe permitir filtrar por moneda, idioma, país y región.

## Qué se comprobó en la API pública (10 nov 2026)

| Pregunta | Resultado |
|---|---|
| ¿Da el país del cliente? | **No.** Sin cuenta autenticada, `owner_id` llega vacío y no hay datos de usuario. |
| ¿`currency.country` es el país del cliente? | **No.** Es el país de la moneda: INR siempre es India. |
| ¿Filtra por skill con `jobs[]`? | Sí. Varias skills se combinan con O: Google Ads 64 + Facebook Ads 49 = 104. |
| ¿Filtra por fecha con `from_time`? | Sí: todos los resultados eran posteriores a la fecha pedida. |
| ¿Informa cuántos resultados hay? | Sí, con `total_count`. |
| ¿Hay taxonomía de skills? | Sí, en `/api/projects/0.1/jobs/`, con ID, nombre y categoría. |

## Decisiones

- **País:** el clasificador extrae `client_country` solo si la publicación lo dice explícitamente. Si no hay, se usa el país de la moneda, marcado como aproximado (≈). Obtener el país real del cliente exigiría una cuenta autenticada, que el PRD no permite.
- **Región:** sale del país según `config/regiones.yaml`. Lo que no figura cuenta como «Otra».
- **Incremental:** no actualiza propuestas ni estados de proyectos antiguos (RF-ING-07). Conviene una corrida `--full` a la semana.
- **Cobertura:** `max_pages` limita lo descargado por búsqueda. Una cobertura baja indica que hay que subirlo o acotar la búsqueda.
- **Palabras clave:** se mantienen solo para español y portugués; las skills cubren el resto sin depender del idioma.

## Cambios del 11 nov 2026

- **Cobertura:** `max_pages` pasa de 5 a 13, suficiente para la búsqueda más grande medida (611 proyectos). Se quita «design de site», con 1.395 resultados y mucho ruido.
- **Reglas v2 del clasificador:** descartan sin IA lo que no tiene ninguna skill del perfil ni ninguna palabra del tema. Medidas contra 1.171 clasificaciones de la IA: ahorran un 5 % de llamadas sin perder ningún proyecto relevante. Una regla más agresiva ahorraba un 15 % pero perdía un 2,2 % de los relevantes, y se descartó.
- **Bloqueo de ejecución:** la ingesta, la clasificación, el rating y el pipeline usan un bloqueo de Postgres; una segunda ejecución simultánea termina con estado `ocupado`.

## Pendiente

- Programar el pipeline en el Programador de tareas de Windows (pendiente de autorización).
- Explorar otros endpoints públicos: concursos (`contests`) y detalle de proyecto.
