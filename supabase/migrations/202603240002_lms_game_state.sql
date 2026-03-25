-- Migration: LMS game state tables

-- Each LMS game instance (you might run multiple per season)
CREATE TABLE IF NOT EXISTS lms_games (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text        NOT NULL DEFAULT 'Game',
  status      text        NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'won', 'eliminated')),
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Teams already picked in each game
CREATE TABLE IF NOT EXISTS lms_picks (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id     uuid        NOT NULL REFERENCES lms_games(id) ON DELETE CASCADE,
  gameweek    integer     NOT NULL,
  team_id     uuid        NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
  result      text        CHECK (result IN ('W', 'L', 'D', NULL)),
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (game_id, gameweek)
);

-- Allow controlling which gameweeks to include in the solver horizon.
-- If a row exists with included=false, that GW is excluded.
CREATE TABLE IF NOT EXISTS lms_gameweek_config (
  game_id     uuid        NOT NULL REFERENCES lms_games(id) ON DELETE CASCADE,
  gameweek    integer     NOT NULL,
  included    boolean     NOT NULL DEFAULT true,
  PRIMARY KEY (game_id, gameweek)
);

ALTER TABLE lms_games ENABLE ROW LEVEL SECURITY;
ALTER TABLE lms_picks ENABLE ROW LEVEL SECURITY;
ALTER TABLE lms_gameweek_config ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public can read lms_games" ON lms_games;
CREATE POLICY "Public can read lms_games" ON lms_games FOR SELECT USING (true);
DROP POLICY IF EXISTS "Public can read lms_picks" ON lms_picks;
CREATE POLICY "Public can read lms_picks" ON lms_picks FOR SELECT USING (true);
DROP POLICY IF EXISTS "Public can read lms_gameweek_config" ON lms_gameweek_config;
CREATE POLICY "Public can read lms_gameweek_config" ON lms_gameweek_config FOR SELECT USING (true);
