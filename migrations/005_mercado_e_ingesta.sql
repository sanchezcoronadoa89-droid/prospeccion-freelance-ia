-- Filtros por idioma, moneda, pais y region; ingesta incremental con cobertura medida.
ALTER TABLE projects
  ADD COLUMN language TEXT,
  ADD COLUMN currency_country TEXT;

-- Pais del cliente o de su mercado, solo si la publicacion lo dice (lo extrae el clasificador).
ALTER TABLE classifications ADD COLUMN client_country TEXT CHECK (client_country ~ '^[A-Z]{2}$');

ALTER TABLE runs
  ADD COLUMN mode TEXT NOT NULL DEFAULT 'completa' CHECK (mode IN ('completa','incremental')),
  ADD COLUMN since TIMESTAMPTZ,
  ADD COLUMN query_stats JSONB NOT NULL DEFAULT '[]';
