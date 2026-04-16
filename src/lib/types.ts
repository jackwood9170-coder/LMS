/* ---- Database row types ---- */

export interface Team {
  id: string
  name: string
  current_elo: number
}

export interface Fixture {
  id: string
  home_team_id: string
  away_team_id: string
  kickoff: string
  gameweek: number | null
  has_odds: boolean
}

export interface MarketOddsRow {
  fixture_id: string
  bookmaker_key: string
  outcome_name: string
  outcome_price: number
}

/* ---- Derived / UI types ---- */

export interface FixtureComparison {
  id: string
  homeTeam: string
  awayTeam: string
  homeElo: number
  awayElo: number
  kickoff: string
  gameweek: number | null
  hasOdds: boolean
  model: { home: number; draw: number; away: number }
  market: { home: number; draw: number; away: number } | null
  diff: { home: number; draw: number; away: number } | null
  source: string | null
}

/* ---- LMS types ---- */

export interface LMSGame {
  id: string
  name: string
  status: string
  created_at: string
  picks: LMSPick[]
  gw_config: Record<number, boolean>
}

export interface LMSPick {
  gameweek: number
  team_id: string
  result: string | null
}

/* ---- Solver response types ---- */

export interface SolverResult {
  game_id: string
  current_gw: number
  horizon: number
  expected_duration: number
  survival_prob: number
  picks_plan: SolverPick[]
  all_options: SolverOption[]
  used_teams: UsedTeam[]
  included_gws: number[]
  excluded_gws: number[]
}

export interface SolverPick {
  gameweek: number
  team_id?: string
  team_name: string | null
  opponent_name?: string
  is_home?: boolean
  win_prob: number
  team_elo?: number
  opponent_elo?: number
  source?: string
}

export interface SolverOption {
  team_id: string
  team_name: string
  opponent_name: string
  is_home: boolean
  win_prob: number
  team_elo: number
  opponent_elo: number
  source: string
}

export interface UsedTeam {
  gameweek: number
  team_name: string
  team_id: string
  result: string | null
}
