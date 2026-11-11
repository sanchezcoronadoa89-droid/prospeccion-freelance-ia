# Qué significa cada dato de la bandeja

Guía de referencia para leer y filtrar los proyectos. Quién decide cada dato importa: lo que viene de la API es un hecho, lo del agente es una interpretación sin medir todavía y lo aproximado es una estimación.

## Categoría

La decide el agente clasificador (o una regla, si no hay ninguna señal). Es el **entregable principal** del encargo, una sola opción.

| Categoría | Qué incluye | Ejemplo |
|---|---|---|
| Marketing | Publicidad, captación, email, analítica y medición, contenido, redes | Configurar GA4 y conversiones; campaña de Meta Ads |
| SEO | Auditorías, palabras clave, SEO técnico o local, enlaces | Auditoría técnica de una tienda |
| IA y automatización | Chatbots, flujos con n8n o Zapier, integraciones sencillas con IA | Chatbot de atención conectado a WhatsApp |
| Web simple | Landings y webs en WordPress, Shopify o similares, sin desarrollo a medida | Landing en WordPress con formulario |
| UX/UI | Diseño de interfaces y experiencia de usuario | Wireframes y prototipo en Figma |
| Otra | Todo lo demás, aunque mencione estos temas de pasada | App a medida «con buen SEO»; logo; vídeo |

Si la categoría la puso una regla, el detalle dice «reglas»: solo ocurre cuando el texto no tiene ninguna señal de estos temas, y siempre es «Otra».

## Relevancia (0 a 1)

Cuánto encaja con tu perfil, según el agente. No tiene en cuenta presupuesto ni competencia.

| Valor | Significado |
|---|---|
| 0,8 a 1 | Tu especialidad: podrías entregarlo hoy |
| 0,5 a 0,7 | Podrías cubrirlo con riesgo razonable, ayudándote de IA |
| 0,2 a 0,4 | Encaje dudoso |
| 0 a 0,1 | Sin relación con tu perfil |

Desde 0,5 un proyecto se considera relevante y recibe rating.

## Complejidad

Esfuerzo y riesgo técnico del encargo en sí, no según tu experiencia. Es el eje de esfuerzo de tu matriz.

- **Baja:** herramientas o plantillas, entregables claros.
- **Media:** algo de código o integraciones, riesgo manejable.
- **Alta:** arquitectura a medida, sistemas críticos o mucha responsabilidad técnica.

## Rating (0 a 100)

Lo bien planteada que está la publicación, no lo atractiva que es. El agente puntúa cuatro criterios de 0 a 5 y **el código calcula la nota** con los pesos de `config/rubrica_calidad_v1.yaml`: alcance (35), entregables (30), coherencia del presupuesto (20) y plazos (15). Resta 15 puntos si pide trabajo gratis de prueba y otros 15 si pide contactar fuera de la plataforma.

## Mercado: país y región

- **País sin ≈:** la publicación lo dice explícitamente («empresa en México»). Lo extrae el agente.
- **País con ≈:** la publicación no lo dice; es el **país de la moneda**. Un proyecto en USD aparece como Estados Unidos aunque el cliente esté en otro lugar. Úsalo con cautela.
- **Región:** se calcula a partir del país según `config/regiones.yaml`. «Otra» agrupa los países que no figuran en esa lista.

La API pública de Freelancer no da el país del cliente: haría falta una cuenta autenticada, que el PRD no permite.

## Moneda e idioma

Vienen directamente de la API: son datos, no interpretaciones. «Máx. USD» es el presupuesto máximo convertido con el tipo de cambio que da la propia API.
