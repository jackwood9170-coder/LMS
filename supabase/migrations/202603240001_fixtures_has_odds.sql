-- Migration: Add has_odds flag to fixtures

ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS has_odds boolean NOT NULL DEFAULT false;

-- Back-fill: mark any fixture that already has h2h market_odds rows
UPDATE fixtures
SET has_odds = true
WHERE id IN (
  SELECT DISTINCT fixture_id
  FROM market_odds
  WHERE market_key = 'h2h'
);
