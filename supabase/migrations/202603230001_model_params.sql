-- Migration: key-value store for calibrated model parameters (HFA, draw boundary, etc.)

CREATE TABLE IF NOT EXISTS model_params (
  key        text           PRIMARY KEY,
  value      numeric(12,4)  NOT NULL,
  updated_at timestamptz    NOT NULL DEFAULT now()
);

ALTER TABLE model_params ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public can read model_params" ON model_params;
CREATE POLICY "Public can read model_params"
  ON model_params FOR SELECT
  USING (true);
