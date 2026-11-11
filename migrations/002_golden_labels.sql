-- Etiquetas del golden set: cada persona etiqueta una version de la muestra en una o dos pasadas.
-- Las correcciones de la auditoria dejan estas columnas vacias.
ALTER TABLE labels
  ADD COLUMN golden_version TEXT,
  ADD COLUMN label_pass SMALLINT CHECK (label_pass IN (1, 2));

CREATE UNIQUE INDEX one_golden_label ON labels (golden_version, author, label_pass, project_id, field)
  WHERE golden_version IS NOT NULL;
