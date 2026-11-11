-- Presupuesto y borrador de propuesta por proyecto (fase 3 adelantada a peticion del titular).
-- Las cifras las calcula el codigo; la IA solo identifica tareas y redacta. Nunca se envia nada.
CREATE TABLE proposals (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT NOT NULL REFERENCES projects(id),
  summary TEXT,
  tasks JSONB NOT NULL,
  missing_info JSONB NOT NULL DEFAULT '[]',
  questions JSONB NOT NULL DEFAULT '[]',
  red_flags JSONB NOT NULL DEFAULT '[]',
  scenarios JSONB NOT NULL,
  recommended_price_usd NUMERIC(12,2),
  recommended_price_local NUMERIC(14,2),
  currency TEXT,
  delivery_days INTEGER,
  draft TEXT,
  draft_language TEXT,
  warnings JSONB NOT NULL DEFAULT '[]',
  params_version TEXT NOT NULL,
  calibrated BOOLEAN NOT NULL,
  model TEXT,
  prompt_version TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX proposals_project ON proposals (project_id, id DESC);
