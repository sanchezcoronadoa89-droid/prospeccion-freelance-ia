-- Permite reutilizar resultados por hash del contenido y comparar versiones.
ALTER TABLE classifications ADD COLUMN content_hash TEXT;
ALTER TABLE ratings ADD COLUMN content_hash TEXT;
ALTER TABLE ratings ADD COLUMN prompt_version TEXT;
CREATE INDEX classifications_project ON classifications (project_id, id DESC);
CREATE INDEX ratings_target ON ratings (target_type, target_id, id DESC);
CREATE INDEX agent_calls_run ON agent_calls (run_id);
