-- Una corrida cuyo proceso murio (apagado, cierre, fallo) quedaba en 'en_curso' para siempre.
-- La siguiente ingesta, que tiene el bloqueo del pipeline, la cierra como 'interrumpida'.
ALTER TABLE runs DROP CONSTRAINT runs_status_check;
ALTER TABLE runs ADD CONSTRAINT runs_status_check
  CHECK (status IN ('en_curso','ok','parcial','bloqueada','cambio_estructura','interrumpida'));
