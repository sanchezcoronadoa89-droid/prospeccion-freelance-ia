// Fuente unica de las explicaciones de la bandeja. La version larga esta en docs/categorias.md.
// Los pesos del rating no estan aqui: se leen de /api/rubric para no tener dos versiones.

// Procedencia: cuanto puedes fiarte de un dato depende de quien lo produce.
export const ORIGINS = {
  api: { label: "Dato de Freelancer", text: "Lo publica la plataforma tal cual. Es un hecho." },
  code: { label: "Cálculo", text: "Lo calcula el código con reglas fijas: siempre da el mismo resultado." },
  agent: { label: "Interpretación de IA", text: "Lo decide un agente leyendo el texto. Todavía no se ha medido cuánto acierta." },
};

export const CATEGORIES = [
  {
    key: "marketing", label: "Marketing",
    includes: "Publicidad, captación, email, analítica y medición, contenido y redes sociales.",
    example: "Configurar GA4 y las conversiones de una tienda online.",
  },
  {
    key: "seo", label: "SEO",
    includes: "Auditorías, palabras clave, SEO técnico o local y enlaces.",
    example: "Auditoría técnica de una tienda en Shopify.",
  },
  {
    key: "ia_automatizacion", label: "IA y automatización",
    includes: "Chatbots, flujos con n8n, Zapier o Make e integraciones sencillas con IA.",
    example: "Chatbot de WhatsApp que responde preguntas frecuentes.",
  },
  {
    key: "web_simple", label: "Web simple",
    includes: "Landings y webs en WordPress, Shopify o similares, sin desarrollo a medida.",
    example: "Landing en WordPress con formulario de contacto.",
  },
  {
    key: "ux_ui", label: "UX/UI",
    includes: "Diseño de interfaces y experiencia: wireframes, prototipos, rediseño visual, investigación.",
    example: "Prototipo en Figma de una app de reservas.",
  },
  {
    key: "otra", label: "Otra",
    includes: "Todo lo demás, aunque mencione alguno de estos temas de pasada.",
    example: "App a medida «con buen SEO», un logo o edición de vídeo.",
  },
];

export const CATEGORY_LABEL = Object.fromEntries(CATEGORIES.map((c) => [c.key, c.label]));

// De mayor a menor: el primer tramo cuyo minimo se alcanza describe el valor.
export const RELEVANCE_BANDS = [
  { min: 0.8, label: "Tu especialidad", text: "Podrías entregarlo hoy." },
  { min: 0.5, label: "Cubrible", text: "Con riesgo razonable, ayudándote de IA." },
  { min: 0.2, label: "Dudoso", text: "Pide conocimientos que probablemente no tienes." },
  { min: 0, label: "Sin relación", text: "No tiene que ver con tu perfil." },
];
export const RELEVANCE_THRESHOLD = 0.5;

export function relevanceBand(value) {
  return RELEVANCE_BANDS.find((band) => value >= band.min) ?? RELEVANCE_BANDS.at(-1);
}

export const COMPLEXITY = [
  { key: "baja", label: "Baja", level: 1, text: "Herramientas o plantillas, con entregables claros." },
  { key: "media", label: "Media", level: 2, text: "Algo de código o integraciones, con riesgo manejable." },
  { key: "alta", label: "Alta", level: 3, text: "Desarrollo a medida, sistemas críticos o mucha responsabilidad técnica." },
];

export const RATING_CRITERIA = {
  scope: "Alcance claro",
  deliverables: "Entregables concretos",
  budget: "Presupuesto coherente con lo pedido",
  timeline: "Plazos",
};
export const RATING_PENALTIES = {
  free_work: "Pide trabajo gratis de prueba",
  off_platform: "Pide contactar o pagar fuera de la plataforma",
};

// Una ficha por columna de la bandeja.
export const FIELDS = {
  "Categoría": {
    origin: "agent",
    short: "El entregable principal del encargo, en una sola categoría.",
    more: "Si el texto no tiene ninguna señal de estos temas, una regla la marca como «Otra» sin usar IA.",
  },
  "Relev.": {
    origin: "agent",
    short: "De 0 a 1, cuánto encaja con tu perfil. Desde 0,5 se considera relevante y recibe nota de calidad.",
    more: "No tiene en cuenta el presupuesto ni la competencia: eso se mira en otras columnas.",
  },
  "Compl.": {
    origin: "agent",
    short: "Esfuerzo y riesgo técnico del encargo en sí, no según tu experiencia.",
    more: "Es el eje de esfuerzo de tu matriz esfuerzo-rentabilidad.",
  },
  "Rating": {
    origin: "agent",
    short: "De 0 a 100, lo bien planteada que está la publicación, no lo atractiva que es.",
    more: "La IA puntúa cuatro criterios y el código calcula la nota. Abre un proyecto para ver su desglose.",
  },
  "Mercado": {
    origin: "agent",
    short: "País y región del cliente.",
    more: "Sin ≈, la publicación lo dice. Con ≈, es el país de la moneda: Freelancer no da el país del cliente.",
  },
  "Presupuesto": {
    origin: "api",
    short: "Rango que indica el cliente, en su moneda.",
    more: "Muchos clientes eligen rangos predefinidos: orienta, pero no es el precio real.",
  },
  "Máx. USD": {
    origin: "code",
    short: "Presupuesto máximo convertido a dólares.",
    more: "Usa el tipo de cambio que da la propia API.",
  },
  "Propuestas": {
    origin: "api",
    short: "Cuántas propuestas ha recibido: es tu competencia.",
    more: "Crece con el tiempo; compárala con la fecha de publicación.",
  },
  "Publicado": {
    origin: "api",
    short: "Fecha y hora de publicación, en tu zona horaria.",
  },
  "Corrida": {
    origin: "code",
    short: "La ingesta que trajo o actualizó el proyecto por última vez.",
    more: "Sirve para saber de dónde sale cada dato.",
  },
};

// La guia se ordena por las preguntas que te haces al revisar un proyecto.
export const QUESTIONS = [
  { question: "¿Qué es?", fields: ["Categoría"] },
  { question: "¿Me encaja?", fields: ["Relev.", "Compl."] },
  { question: "¿Está bien planteado?", fields: ["Rating"] },
  { question: "¿Dónde y por cuánto?", fields: ["Mercado", "Presupuesto", "Máx. USD"] },
  { question: "¿Cuánta competencia hay?", fields: ["Propuestas", "Publicado"] },
  { question: "¿De dónde sale?", fields: ["Corrida"] },
];

export const FIELD_TITLES = {
  "Relev.": "Relevancia",
  "Compl.": "Complejidad",
};
