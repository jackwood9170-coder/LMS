-- Add denormalised team name columns to fixtures for readability
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS home_team_name text;
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS away_team_name text;

-- Backfill from teams table
UPDATE fixtures f
SET home_team_name = t.name
FROM teams t
WHERE f.home_team_id = t.id
  AND f.home_team_name IS NULL;

UPDATE fixtures f
SET away_team_name = t.name
FROM teams t
WHERE f.away_team_id = t.id
  AND f.away_team_name IS NULL;
