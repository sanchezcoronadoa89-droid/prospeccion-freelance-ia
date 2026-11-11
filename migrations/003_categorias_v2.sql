-- Categorias v2 y complejidad, para el eje de esfuerzo de la matriz esfuerzo-rentabilidad.
ALTER TABLE classifications DROP CONSTRAINT classifications_category_check;
ALTER TABLE classifications ADD CONSTRAINT classifications_category_check
  CHECK (category IN ('marketing','seo','ia_automatizacion','web_simple','ux_ui','otra'));
ALTER TABLE classifications
  ADD COLUMN complexity TEXT CHECK (complexity IN ('baja','media','alta'));
