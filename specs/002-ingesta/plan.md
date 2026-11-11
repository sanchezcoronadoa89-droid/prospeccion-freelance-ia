# 002 · Plan

Flujo de `scripts/ingest.py`: sincronizar registro → puerta legal → crear corrida → comprobar robots.txt → paginar → guardar snapshot filtrado → parsear → comprobar estructura → filtrar → deduplicar → guardar y versionar → cerrar corrida.

## Verificado y pendiente

Comprobado con una consulta real: ruta `/api/projects/0.1/projects/active/`, acceso sin token y campos `id`, `title`, `status`, `seo_url`, `currency`, `submitdate`, `preview_description`, `type`, `budget` y `bid_stats`. Sin parámetros extra, `description`, `jobs` y `owner_id` llegaron nulos.

Comprobado en la corrida #1: `full_description`, `job_details` y `languages[]` se aceptan, y llegan `description`, `jobs` y `language` en los 436 proyectos.

Pendiente:

- Cómo obtener país y pago verificado sin guardar datos del usuario. `client_country` y `client_payment_verified` quedan vacíos por ahora.
- Los límites de tasa reales de la API. La documentación oficial no se pudo consultar.

## Riesgos conocidos

- La detección de contactos en texto libre es por patrones: reduce el riesgo, pero no lo elimina.
- Los snapshots no están cifrados; la sección 5 de los términos pide cifrado fuerte para los datos almacenados.
