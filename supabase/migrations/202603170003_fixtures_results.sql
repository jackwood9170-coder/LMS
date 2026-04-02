-- Migration: Add match result columns and football-data.co.uk dedup key to fixtures

-- Result columns (NULL for future/unplayed fixtures)
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS home_goals    integer;
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS away_goals    integer;
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS result        text CHECK (result IN ('H', 'D', 'A'));
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS ht_home_goals integer;
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS ht_away_goals integer;

-- Dedup key for football-data.co.uk rows: "{HomeTeam}_{AwayTeam}_{DD/MM/YYYY}"
-- Allows safe upsert without relying on odds_api_event_id (which won't exist
-- for historically-sourced fixtures).
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS fdco_match_key text UNIQUE;
