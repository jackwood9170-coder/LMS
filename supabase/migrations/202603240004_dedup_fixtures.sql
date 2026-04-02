-- Fix duplicate fixtures caused by The Odds API generating new event IDs
-- when kickoff times change.
--
-- Strategy: for each (home_team_id, away_team_id) pair with duplicates,
-- keep the row with the most recent created_at (latest data) and delete
-- the rest. Then add a unique constraint to prevent future duplicates.

-- Step 1: Delete older duplicates, keeping the newest row per matchup
DELETE FROM fixtures
WHERE id IN (
  SELECT id FROM (
    SELECT id,
           ROW_NUMBER() OVER (
             PARTITION BY home_team_id, away_team_id
             ORDER BY created_at DESC
           ) AS rn
    FROM fixtures
  ) ranked
  WHERE rn > 1
);

-- Step 2: Add unique constraint so this can't happen again
ALTER TABLE fixtures
  ADD CONSTRAINT uq_fixtures_home_away
  UNIQUE (home_team_id, away_team_id);
