"""
calibrate_elo.py
----------------
Reverse-engineers ELO ratings for each EPL team by fitting the ELO model to
de-vigged closing odds from completed 2025/26 fixtures.

Odds priority per fixture (h2h market):
  1. Pinnacle closing  (bookmaker_key = 'pinnacle_closing')
  2. Bet365 closing    (bookmaker_key = 'bet365_closing')
  3. Market average    (bookmaker_key = 'market_avg')

Method:
  - De-vig each selected bookmaker's 1X2 odds via basic normalisation.
  - Fit 20 team ELO ratings + 1 home-field-advantage constant using
    scipy.optimize.minimize (L-BFGS-B), minimising log-loss between
    ELO-predicted win probabilities and market-implied probabilities.
  - Anchor: mean team rating constrained to 1500.
  - Write calibrated ratings back to teams.current_elo in Supabase.

Usage:
  python scripts/calibrate_elo.py

Required environment variables (see .env):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
"""

import os
import logging
from datetime import datetime, timezone
import numpy as np
from scipy.optimize import minimize
from dotenv import load_dotenv
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# ELO scale factor — standard value; higher = ratings spread further apart
ELO_SCALE = 400.0

# Bookmaker priority for odds selection
BOOKMAKER_PRIORITY = ["pinnacle_closing", "bet365_closing", "market_avg"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_fixtures(sb: Client) -> list[dict]:
    """Load all completed fixtures with home/away team ids."""
    result = (
        sb.table("fixtures")
        .select("id, home_team_id, away_team_id")
        .eq("status", "completed")
        .execute()
    )
    return result.data


def load_h2h_odds(sb: Client, fixture_ids: list[str]) -> dict[str, dict]:
    """
    For each fixture, return the best available bookmaker's 1X2 closing odds.
    Returns: { fixture_id: {"outcomes": dict, "source": str} }
    """
    # Supabase REST .in_() serialises IDs into the URL; chunking avoids the
    # ~8 KB URL limit that silently truncates large ID lists.
    CHUNK = 50
    all_rows: list[dict] = []
    for i in range(0, len(fixture_ids), CHUNK):
        chunk = fixture_ids[i : i + CHUNK]
        result = (
            sb.table("market_odds")
            .select("fixture_id, bookmaker_key, outcome_name, outcome_price")
            .eq("market_key", "h2h")
            .in_("bookmaker_key", BOOKMAKER_PRIORITY)
            .in_("fixture_id", chunk)
            .execute()
        )
        all_rows.extend(result.data)

    # Group by fixture_id → bookmaker_key → outcome
    raw: dict[str, dict[str, dict[str, float]]] = {}
    for row in all_rows:
        fid = row["fixture_id"]
        bk  = row["bookmaker_key"]
        raw.setdefault(fid, {}).setdefault(bk, {})[row["outcome_name"]] = float(row["outcome_price"])

    # Pick best bookmaker per fixture using priority order
    best: dict[str, dict] = {}
    for fid, bk_map in raw.items():
        for bk in BOOKMAKER_PRIORITY:
            outcomes = bk_map.get(bk, {})
            # Need all three outcomes
            prices = list(outcomes.values())
            if len(prices) == 3:
                # Map by outcome name — we stored home team name, Draw, away team name
                # We'll normalise without needing to know which key is home/draw/away
                # by returning the raw dict; caller resolves using fixture team names
                best[fid] = {"outcomes": outcomes, "source": bk}
                break

    return best


def load_teams(sb: Client) -> dict[str, str]:
    """Return {team_id: team_name}."""
    result = sb.table("teams").select("id, name").execute()
    return {r["id"]: r["name"] for r in result.data}


# All known name variants across football-data.co.uk and The Odds API.
# Maps any stored outcome_name variant → canonical team name.
_ALIASES: dict[str, str] = {
    # football-data.co.uk short names
    "Man United":             "Manchester United",
    "Man City":               "Manchester City",
    "Brighton":               "Brighton and Hove Albion",
    "Nott'm Forest":          "Nottingham Forest",
    "Newcastle":              "Newcastle United",
    "West Ham":               "West Ham United",
    "Wolves":                 "Wolverhampton Wanderers",
    "Spurs":                  "Tottenham Hotspur",
    "Tottenham":              "Tottenham Hotspur",
    "Leeds":                  "Leeds United",
    "Leicester":              "Leicester City",
    "Norwich":                "Norwich City",
    "Ipswich":                "Ipswich Town",
    "Sheffield Weds":         "Sheffield Wednesday",
    "QPR":                    "Queens Park Rangers",
    "Huddersfield":           "Huddersfield Town",
    "Cardiff":                "Cardiff City",
    "Stoke":                  "Stoke City",
    "Swansea":                "Swansea City",
    "Coventry":               "Coventry City",
    # Odds API variants
    "Brighton & Hove Albion": "Brighton and Hove Albion",
    "Nottingham Forest":      "Nottingham Forest",
    "Wolverhampton":          "Wolverhampton Wanderers",
    "Sunderland AFC":         "Sunderland",
}


def build_alias_map(teams_map: dict[str, str]) -> dict[str, str]:
    """
    Return a dict: any outcome_name variant → team_id.
    Priority: exact canonical name match, then explicit alias table.
    """
    name_to_id = {name: tid for tid, name in teams_map.items()}
    alias_to_id: dict[str, str] = dict(name_to_id)  # canonical names first

    for alias, canonical in _ALIASES.items():
        if canonical in name_to_id and alias not in alias_to_id:
            alias_to_id[alias] = name_to_id[canonical]

    return alias_to_id


def find_outcome_price(
    outcomes: dict[str, float],
    team_id: str,
    alias_to_id: dict[str, str],
) -> float | None:
    """
    Find the price for a team in an outcomes dict, regardless of which name
    variant was stored. Matches by resolving outcome_name → team_id.
    """
    for outcome_name, price in outcomes.items():
        if alias_to_id.get(outcome_name) == team_id:
            return price
    return None


# ---------------------------------------------------------------------------
# De-vig
# ---------------------------------------------------------------------------

def devIG(odds_h: float, odds_d: float, odds_a: float) -> tuple[float, float, float]:
    """Basic normalisation de-vig. Returns (p_home, p_draw, p_away)."""
    inv_h, inv_d, inv_a = 1 / odds_h, 1 / odds_d, 1 / odds_a
    overround = inv_h + inv_d + inv_a
    return inv_h / overround, inv_d / overround, inv_a / overround


# ---------------------------------------------------------------------------
# ELO model
# ---------------------------------------------------------------------------

def elo_1x2(
    rating_home: float, rating_away: float, hfa: float, draw_boundary: float,
) -> tuple[float, float, float]:
    """1X2 probabilities from Elo ratings using a draw-boundary model.

    P(home) = 1 / (1 + 10^(-(dr - D) / S))
    P(away) = 1 / (1 + 10^( (dr + D) / S))
    P(draw) = 1 - P(home) - P(away)

    where dr = rating_home + hfa - rating_away, D = draw_boundary, S = ELO_SCALE.
    """
    dr = rating_home + hfa - rating_away
    p_home = 1.0 / (1.0 + 10.0 ** (-(dr - draw_boundary) / ELO_SCALE))
    p_away = 1.0 / (1.0 + 10.0 ** ((dr + draw_boundary) / ELO_SCALE))
    p_draw = 1.0 - p_home - p_away
    return p_home, p_draw, p_away


# ---------------------------------------------------------------------------
# Objective function
# ---------------------------------------------------------------------------

def build_objective(fixtures_data: list[dict]):
    """
    Returns a closure over the fixture data.
    fixtures_data: list of {home_idx, away_idx, p_home, p_draw, p_away}
    The parameter vector x = [r_0, r_1, ..., r_{n-1}, hfa, draw_boundary]
    """
    eps = 1e-9  # clip to avoid log(0)

    def objective(x: np.ndarray) -> float:
        ratings = x[:-2]
        hfa = x[-2]
        draw_boundary = x[-1]
        loss = 0.0
        for fd in fixtures_data:
            r_h = ratings[fd["home_idx"]]
            r_a = ratings[fd["away_idx"]]
            e_h, e_d, e_a = elo_1x2(r_h, r_a, hfa, draw_boundary)
            e_h = np.clip(e_h, eps, 1 - eps)
            e_d = np.clip(e_d, eps, 1 - eps)
            e_a = np.clip(e_a, eps, 1 - eps)
            # Log-loss against market-implied 1X2 probabilities
            loss += -(
                fd["p_home"] * np.log(e_h)
                + fd["p_draw"] * np.log(e_d)
                + fd["p_away"] * np.log(e_a)
            )
        return loss

    return objective


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("Connecting to Supabase: %s", SUPABASE_URL)
    sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    log.info("Loading fixtures and teams …")
    fixtures   = load_fixtures(sb)
    teams_map  = load_teams(sb)   # {id: name}

    fixture_ids = [f["id"] for f in fixtures]
    log.info("Loaded %d completed fixtures, %d teams", len(fixtures), len(teams_map))

    log.info("Loading h2h odds (Pinnacle → Bet365 → Market Avg) …")
    odds_map = load_h2h_odds(sb, fixture_ids)
    log.info("Odds found for %d / %d fixtures", len(odds_map), len(fixtures))

    # Build sorted team list for consistent index mapping
    team_ids   = sorted(teams_map.keys())
    team_index = {tid: i for i, tid in enumerate(team_ids)}
    n_teams    = len(team_ids)

    alias_to_id = build_alias_map(teams_map)

    # Build training data
    training: list[dict] = []
    skipped = 0
    unresolved: list[str] = []
    sources: dict[str, int] = {}

    for fixture in fixtures:
        fid  = fixture["id"]
        htid = fixture["home_team_id"]
        atid = fixture["away_team_id"]

        if fid not in odds_map:
            skipped += 1
            continue
        if htid not in team_index or atid not in team_index:
            skipped += 1
            continue

        entry    = odds_map[fid]
        outcomes = entry["outcomes"]
        source   = entry["source"]
        sources[source] = sources.get(source, 0) + 1

        # Resolve by team_id — immune to name variant differences across sources
        odds_h = find_outcome_price(outcomes, htid, alias_to_id)
        odds_d = outcomes.get("Draw")
        odds_a = find_outcome_price(outcomes, atid, alias_to_id)

        if not all([odds_h, odds_d, odds_a]):
            home_name = teams_map.get(htid, htid)
            away_name = teams_map.get(atid, atid)
            stored_names = list(outcomes.keys())
            unresolved.append(
                f"{home_name} vs {away_name} — stored names: {stored_names}"
            )
            skipped += 1
            continue

        p_home, p_draw, p_away = devIG(odds_h, odds_d, odds_a)

        training.append({
            "home_idx": team_index[htid],
            "away_idx": team_index[atid],
            "p_home":   p_home,
            "p_draw":   p_draw,
            "p_away":   p_away,
        })

    log.info(
        "Training set: %d fixtures  (skipped %d)",
        len(training), skipped,
    )
    if unresolved:
        log.warning("%d fixtures skipped — could not resolve team names:", len(unresolved))
        for msg in unresolved:
            log.warning("  %s", msg)
    log.info("Odds sources used: %s", sources)

    if not training:
        log.error("No training data — cannot calibrate. Exiting.")
        return

    # ---------------------------------------------------------------------------
    # Optimisation
    # ---------------------------------------------------------------------------
    # Initial values: all teams at 1500, HFA=65 Elo pts, draw boundary=85 Elo pts
    x0 = np.array([1500.0] * n_teams + [65.0, 85.0])

    # Constraint: mean rating = 1500
    constraints = {
        "type": "eq",
        "fun": lambda x: np.mean(x[:-2]) - 1500.0,
    }

    # Bounds: ratings unbounded, HFA >= 0, draw_boundary >= 1
    bounds = [(None, None)] * n_teams + [(0, None), (1, None)]

    log.info("Running optimisation (%d teams + HFA + draw boundary) …", n_teams)
    result = minimize(
        build_objective(training),
        x0,
        method="SLSQP",
        constraints=constraints,
        bounds=bounds,
        options={"maxiter": 2000, "ftol": 1e-10},
    )

    if not result.success:
        log.warning("Optimiser warning: %s", result.message)
    else:
        log.info("Optimisation converged. Final loss: %.4f", result.fun)

    calibrated_ratings = result.x[:-2]
    hfa = result.x[-2]
    draw_boundary = result.x[-1]
    log.info("Calibrated HFA: %.1f ELO points", hfa)
    log.info("Calibrated draw boundary: %.1f ELO points", draw_boundary)

    # ---------------------------------------------------------------------------
    # Results summary
    # ---------------------------------------------------------------------------
    team_ratings = sorted(
        [(teams_map[team_ids[i]], calibrated_ratings[i]) for i in range(n_teams)],
        key=lambda x: x[1],
        reverse=True,
    )
    log.info("Calibrated ELO ratings:")
    for rank, (name, rating) in enumerate(team_ratings, 1):
        log.info("  %2d. %-35s %.1f", rank, name, rating)

    # ---------------------------------------------------------------------------
    # Write back to Supabase
    # ---------------------------------------------------------------------------
    log.info("Writing ratings to teams.current_elo …")
    for i, tid in enumerate(team_ids):
        sb.table("teams").update(
            {"current_elo": round(float(calibrated_ratings[i]), 2)}
        ).eq("id", tid).execute()

    log.info("Done. %d team ELO ratings updated.", n_teams)

    # Store model parameters
    log.info("Writing model parameters (HFA, draw_boundary) …")
    now = datetime.now(timezone.utc).isoformat()
    for key, value in [("hfa", hfa), ("draw_boundary", draw_boundary)]:
        sb.table("model_params").upsert(
            {"key": key, "value": round(float(value), 4), "updated_at": now},
            on_conflict="key",
        ).execute()
    log.info("Model parameters stored.")


if __name__ == "__main__":
    main()
