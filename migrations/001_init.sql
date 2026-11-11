-- Modelo de datos del PRD (13 tablas). Todo resultado de agente guarda modelo,
-- version de prompt o rubrica y corrida. No se guardan nombres ni contactos.
CREATE TABLE sources (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  base_url TEXT NOT NULL,
  access_mode TEXT NOT NULL CHECK (access_mode IN ('api','feed','email','scraping','manual')),
  legal_status TEXT NOT NULL CHECK (legal_status IN ('permitido','pendiente','prohibido')),
  terms_url TEXT,
  legal_notes TEXT,
  frequency TEXT,
  rate_limit_per_min INTEGER NOT NULL CHECK (rate_limit_per_min > 0),
  active BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE search_profiles (
  id BIGSERIAL PRIMARY KEY,
  source_id BIGINT NOT NULL REFERENCES sources(id),
  version INTEGER NOT NULL,
  criteria JSONB NOT NULL,
  content_hash TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_id, version)
);
CREATE UNIQUE INDEX one_active_profile ON search_profiles (source_id) WHERE active;

CREATE TABLE runs (
  id BIGSERIAL PRIMARY KEY,
  source_id BIGINT NOT NULL REFERENCES sources(id),
  search_profile_id BIGINT NOT NULL REFERENCES search_profiles(id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (status IN ('en_curso','ok','parcial','bloqueada','cambio_estructura')),
  pages INTEGER NOT NULL DEFAULT 0,
  items INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  errors JSONB NOT NULL DEFAULT '[]',
  cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0
);

CREATE TABLE raw_snapshots (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES runs(id),
  url TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  file_path TEXT NOT NULL,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE projects (
  id BIGSERIAL PRIMARY KEY,
  source_id BIGINT NOT NULL REFERENCES sources(id),
  external_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  skills JSONB NOT NULL DEFAULT '[]',
  budget_min NUMERIC(14,2),
  budget_max NUMERIC(14,2),
  currency TEXT,
  usd_rate NUMERIC(14,6),
  project_type TEXT CHECK (project_type IN ('fixed','hourly')),
  posted_at TIMESTAMPTZ,
  bid_count INTEGER,
  status TEXT,
  client_country TEXT,
  client_payment_verified BOOLEAN,
  near_duplicate_of BIGINT REFERENCES projects(id),
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_id, external_id)
);

CREATE TABLE project_versions (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT NOT NULL REFERENCES projects(id),
  snapshot_id BIGINT NOT NULL REFERENCES raw_snapshots(id),
  changed_fields JSONB NOT NULL,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE classifications (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT NOT NULL REFERENCES projects(id),
  run_id BIGINT REFERENCES runs(id),
  category TEXT CHECK (category IN ('ux_ui','seo','ambas','otra')),
  subcategories JSONB NOT NULL DEFAULT '[]',
  language TEXT,
  relevance NUMERIC(4,3) CHECK (relevance BETWEEN 0 AND 1),
  justification TEXT,
  needs_review BOOLEAN NOT NULL DEFAULT FALSE,
  model TEXT,
  prompt_version TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ratings (
  id BIGSERIAL PRIMARY KEY,
  target_type TEXT NOT NULL CHECK (target_type IN ('post','source')),
  target_id BIGINT NOT NULL,
  run_id BIGINT REFERENCES runs(id),
  score NUMERIC(5,2) NOT NULL CHECK (score BETWEEN 0 AND 100),
  breakdown JSONB NOT NULL,
  rubric_version TEXT NOT NULL,
  model TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE labels (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT NOT NULL REFERENCES projects(id),
  field TEXT NOT NULL,
  expected_value JSONB NOT NULL,
  author TEXT NOT NULL,
  dataset_split TEXT CHECK (dataset_split IN ('dev','test')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE brief_analyses (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT NOT NULL REFERENCES projects(id),
  run_id BIGINT REFERENCES runs(id),
  sheet JSONB NOT NULL,
  questions JSONB NOT NULL DEFAULT '[]',
  red_flags JSONB NOT NULL DEFAULT '[]',
  model TEXT,
  prompt_version TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE profitability (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT NOT NULL REFERENCES projects(id),
  run_id BIGINT REFERENCES runs(id),
  hours_by_scenario JSONB NOT NULL,
  hourly_rate NUMERIC(12,2) NOT NULL,
  commission NUMERIC(6,4) NOT NULL,
  margin_by_scenario JSONB NOT NULL,
  priority NUMERIC(6,3),
  params_version TEXT NOT NULL,
  model TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE market_metrics (
  id BIGSERIAL PRIMARY KEY,
  week DATE NOT NULL,
  source_id BIGINT NOT NULL REFERENCES sources(id),
  category TEXT NOT NULL,
  median NUMERIC(14,2),
  p25 NUMERIC(14,2),
  p75 NUMERIC(14,2),
  volume INTEGER NOT NULL,
  avg_competition NUMERIC(10,2),
  UNIQUE (week, source_id, category)
);

CREATE TABLE agent_calls (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT REFERENCES runs(id),
  agent TEXT NOT NULL,
  model TEXT,
  prompt_version TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cost_usd NUMERIC(12,6),
  latency_ms INTEGER,
  result TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
