-- Migration: Extend schema for The Odds API integration

-- 1. Make gameweek nullable — the Odds API does not expose gameweek numbers.
--    Existing rows are unaffected; new API-sourced fixtures will have NULL.
ALTER TABLE fixtures ALTER COLUMN gameweek DROP NOT NULL;

-- 2. Add odds_api_event_id for deduplication against The Odds API.
--    Standard UNIQUE column — PostgreSQL allows multiple NULLs so manually
--    created fixtures (without an event id) are unaffected.
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS odds_api_event_id text UNIQUE;

-- 3. market_odds — stores every bookmaker × market × outcome row returned by
--    the API. The unique constraint lets the script upsert safely so each run
--    replaces stale prices in-place.
--
--    Supported market keys (soccer_epl):
--      h2h           – Match winner (1X2)
--      spreads       – Asian handicap (outcome_point = line)
--      totals        – Goals over/under (outcome_point = line)
--      btts          – Both teams to score
--      draw_no_bet   – Draw no bet
CREATE TABLE IF NOT EXISTS market_odds (
  id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  fixture_id      uuid         NOT NULL REFERENCES fixtures(id) ON DELETE CASCADE,
  bookmaker_key   text         NOT NULL,
  bookmaker_title text         NOT NULL,
  market_key      text         NOT NULL,
  outcome_name    text         NOT NULL,
  outcome_price   numeric(10,4) NOT NULL,
  outcome_point   numeric(10,4),           -- spread / totals line; NULL for h2h / btts
  last_update     timestamptz,             -- last bookmaker update reported by the API
  captured_at     timestamptz  NOT NULL DEFAULT now(),

  CONSTRAINT uq_market_odds
    UNIQUE (fixture_id, bookmaker_key, market_key, outcome_name)
);

CREATE INDEX IF NOT EXISTS idx_market_odds_fixture_id ON market_odds(fixture_id);
CREATE INDEX IF NOT EXISTS idx_market_odds_market_key ON market_odds(market_key);

ALTER TABLE market_odds ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public can read market_odds" ON market_odds;
CREATE POLICY "Public can read market_odds"
  ON market_odds FOR SELECT
  USING (true);
