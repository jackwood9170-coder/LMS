"""
compare_elo_vs_market.py
------------------------
Compares Elo-predicted 1X2 probabilities with de-vigged market odds for
upcoming EPL fixtures.

Market odds priority (h2h market):
  1. Pinnacle  (bookmaker_key = 'pinnacle' or 'pinnacle_closing')
  2. Bet365    (bookmaker_key = 'bet365' or 'bet365_closing')
  3. Average across all available bookmakers

The margin is stripped from the raw odds via basic normalisation (sum of
implied probabilities rescaled to 1) to produce comparable raw probabilities.

Usage:
  python scripts/compare_elo_vs_market.py

Required environment variables (see .env):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
"""

import os
import sys
import logging
import numpy as np
from dotenv import load_dotenv
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

ELO_SCALE = 400.0

# Bookmaker priority — first key found with a complete h2h set wins.
# Includes both live (Odds API) and closing (football-data) key variants.
BOOKMAKER_PRIORITY = [
    "pinnacle", "pinnacle_closing",
    "bet365", "bet365_closing",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Elo 1X2 model  (mirrors calibrate_elo.py)
# ---------------------------------------------------------------------------

def elo_1x2(
    rating_home: float, rating_away: float, hfa: float, draw_boundary: float,
) -> tuple[float, float, float]:
    """1X2 probabilities from Elo ratings using a draw-boundary model."""
    dr = rating_home + hfa - rating_away
    p_home = 1.0 / (1.0 + 10.0 ** (-(dr - draw_boundary) / ELO_SCALE))
    p_away = 1.0 / (1.0 + 10.0 ** ((dr + draw_boundary) / ELO_SCALE))
    p_draw = 1.0 - p_home - p_away
    return p_home, p_draw, p_away


# ---------------------------------------------------------------------------
# De-vig
# ---------------------------------------------------------------------------

def devig(odds_h: float, odds_d: float, odds_a: float) -> tuple[float, float, float]:
    """Basic normalisation de-vig.  Returns (p_home, p_draw, p_away)."""
    inv_h, inv_d, inv_a = 1.0 / odds_h, 1.0 / odds_d, 1.0 / odds_a
    overround = inv_h + inv_d + inv_a
    return inv_h / overround, inv_d / overround, inv_a / overround


# ---------------------------------------------------------------------------
# Team name aliases  (mirrors calibrate_elo.py)
# ---------------------------------------------------------------------------

_ALIASES: dict[str, str] = {
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
    "Brighton & Hove Albion": "Brighton and Hove Albion",
    "Nottingham Forest":      "Nottingham Forest",
    "Wolverhampton":          "Wolverhampton Wanderers",
    "Sunderland AFC":         "Sunderland",
}


def build_alias_map(teams_map: dict[str, str]) -> dict[str, str]:
    """Return a dict: any outcome_name variant → team_id."""
    name_to_id = {name: tid for tid, name in teams_map.items()}
    alias_to_id: dict[str, str] = dict(name_to_id)

    for alias, canonical in _ALIASES.items():
        if canonical in name_to_id and alias not in alias_to_id:
            alias_to_id[alias] = name_to_id[canonical]

    return alias_to_id


def find_outcome_price(
    outcomes: dict[str, float],
    team_id: str,
    alias_to_id: dict[str, str],
) -> float | None:
    """Find the price for a team regardless of name variant stored."""
    for outcome_name, price in outcomes.items():
        if alias_to_id.get(outcome_name) == team_id:
            return price
    return None


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_teams(sb: Client) -> dict[str, dict]:
    """Return {team_id: {name, current_elo}}."""
    result = sb.table("teams").select("id, name, current_elo").execute()
    return {r["id"]: r for r in result.data}


def load_model_params(sb: Client) -> dict[str, float]:
    """Return {key: value} from model_params table."""
    result = sb.table("model_params").select("key, value").execute()
    return {r["key"]: float(r["value"]) for r in result.data}


def load_upcoming_fixtures(sb: Client) -> list[dict]:
    """Load all scheduled fixtures ordered by kickoff."""
    result = (
        sb.table("fixtures")
        .select("id, home_team_id, away_team_id, kickoff, gameweek")
        .eq("status", "scheduled")
        .order("kickoff")
        .execute()
    )
    return result.data


def load_h2h_odds(sb: Client, fixture_ids: list[str]) -> dict[str, dict]:
    """
    For each fixture return the best available bookmaker h2h odds.

    Priority: pinnacle → bet365 → average across all bookmakers.
    Returns: {fixture_id: {"outcomes": {name: price}, "source": str}}
    """
    CHUNK = 50
    all_rows: list[dict] = []
    for i in range(0, len(fixture_ids), CHUNK):
        chunk = fixture_ids[i : i + CHUNK]
        result = (
            sb.table("market_odds")
            .select("fixture_id, bookmaker_key, outcome_name, outcome_price")
            .eq("market_key", "h2h")
            .in_("fixture_id", chunk)
            .execute()
        )
        all_rows.extend(result.data)

    # Group: fixture_id → bookmaker_key → {outcome_name: price}
    raw: dict[str, dict[str, dict[str, float]]] = {}
    for row in all_rows:
        fid = row["fixture_id"]
        bk = row["bookmaker_key"]
        raw.setdefault(fid, {}).setdefault(bk, {})[row["outcome_name"]] = float(
            row["outcome_price"]
        )

    best: dict[str, dict] = {}
    for fid, bk_map in raw.items():
        # Try priority bookmakers first
        found = False
        for bk in BOOKMAKER_PRIORITY:
            outcomes = bk_map.get(bk, {})
            if len(outcomes) == 3:
                best[fid] = {"outcomes": outcomes, "source": bk}
                found = True
                break

        if not found:
            # Compute average across all bookmakers with complete h2h sets
            agg: dict[str, list[float]] = {}
            n_books = 0
            for bk, outcomes in bk_map.items():
                if len(outcomes) == 3:
                    for name, price in outcomes.items():
                        agg.setdefault(name, []).append(price)
                    n_books += 1
            if n_books > 0 and len(agg) == 3:
                avg_outcomes = {
                    name: sum(prices) / len(prices) for name, prices in agg.items()
                }
                best[fid] = {
                    "outcomes": avg_outcomes,
                    "source": f"avg ({n_books} books)",
                }

    return best


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def prob_to_odds(p: float) -> str:
    """Convert probability → implied decimal odds string."""
    if p <= 0:
        return "  —  "
    return f"{1.0 / p:.2f}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("Connecting to Supabase: %s", SUPABASE_URL)
    sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # ------------------------------------------------------------------
    # Load model parameters
    # ------------------------------------------------------------------
    params = load_model_params(sb)
    hfa = params.get("hfa")
    draw_boundary = params.get("draw_boundary")
    if hfa is None or draw_boundary is None:
        log.error(
            "Model parameters (hfa, draw_boundary) not found in model_params table. "
            "Run calibrate_elo.py first."
        )
        sys.exit(1)
    log.info("Model params — HFA: %.1f  draw boundary: %.1f", hfa, draw_boundary)

    # ------------------------------------------------------------------
    # Load teams & Elo ratings
    # ------------------------------------------------------------------
    teams = load_teams(sb)
    alias_to_id = build_alias_map({tid: t["name"] for tid, t in teams.items()})
    log.info("Loaded %d teams", len(teams))

    # ------------------------------------------------------------------
    # Load upcoming fixtures
    # ------------------------------------------------------------------
    fixtures = load_upcoming_fixtures(sb)
    if not fixtures:
        log.info("No upcoming (scheduled) fixtures found.")
        sys.exit(0)

    fixture_ids = [f["id"] for f in fixtures]
    log.info("Loaded %d upcoming fixtures", len(fixtures))

    # ------------------------------------------------------------------
    # Load market h2h odds
    # ------------------------------------------------------------------
    odds_map = load_h2h_odds(sb, fixture_ids)
    log.info(
        "H2H odds found for %d / %d fixtures", len(odds_map), len(fixtures)
    )

    # ------------------------------------------------------------------
    # Comparison table
    # ------------------------------------------------------------------
    header = (
        f"{'Match':<45} {'GW':>3}  {'Source':<20}  "
        f"{'Elo H':>6} {'Elo D':>6} {'Elo A':>6}  "
        f"{'Mkt H':>6} {'Mkt D':>6} {'Mkt A':>6}  "
        f"{chr(916)+' H':>6} {chr(916)+' D':>6} {chr(916)+' A':>6}"
    )
    sep = "-" * len(header)

    print(f"\n{header}")
    print(sep)

    abs_errors: list[float] = []  # per-outcome absolute errors
    log_losses: list[float] = []
    eps = 1e-9
    matched = 0

    for fixture in fixtures:
        fid = fixture["id"]
        htid = fixture["home_team_id"]
        atid = fixture["away_team_id"]
        gw = fixture.get("gameweek") or "-"

        home = teams.get(htid)
        away = teams.get(atid)
        if not home or not away:
            continue

        label = f"{home['name']} v {away['name']}"

        # Elo predicted 1X2
        elo_h, elo_d, elo_a = elo_1x2(
            float(home["current_elo"]),
            float(away["current_elo"]),
            hfa,
            draw_boundary,
        )

        # Market odds
        if fid not in odds_map:
            print(
                f"{label:<45} {str(gw):>3}  {'(no odds)':>20}  "
                f"{elo_h:>5.1%} {elo_d:>6.1%} {elo_a:>6.1%}  "
                f"{'—':>6} {'—':>6} {'—':>6}  "
                f"{'—':>6} {'—':>6} {'—':>6}"
            )
            continue

        entry = odds_map[fid]
        outcomes = entry["outcomes"]
        source = entry["source"]

        odds_h = find_outcome_price(outcomes, htid, alias_to_id)
        odds_d = outcomes.get("Draw")
        odds_a = find_outcome_price(outcomes, atid, alias_to_id)

        if not all([odds_h, odds_d, odds_a]):
            log.warning(
                "Could not resolve h2h outcomes for %s — stored names: %s",
                label,
                list(outcomes.keys()),
            )
            continue

        mkt_h, mkt_d, mkt_a = devig(odds_h, odds_d, odds_a)

        d_h = elo_h - mkt_h
        d_d = elo_d - mkt_d
        d_a = elo_a - mkt_a

        print(
            f"{label:<45} {str(gw):>3}  {source:<20}  "
            f"{elo_h:>5.1%} {elo_d:>6.1%} {elo_a:>6.1%}  "
            f"{mkt_h:>5.1%} {mkt_d:>6.1%} {mkt_a:>6.1%}  "
            f"{d_h:>+5.1%} {d_d:>+6.1%} {d_a:>+6.1%}"
        )

        # Accumulate error metrics
        abs_errors.extend([abs(d_h), abs(d_d), abs(d_a)])
        for p_elo, p_mkt in [(elo_h, mkt_h), (elo_d, mkt_d), (elo_a, mkt_a)]:
            p_elo_c = np.clip(p_elo, eps, 1 - eps)
            log_losses.append(-p_mkt * np.log(p_elo_c))
        matched += 1

    print(sep)

    # ------------------------------------------------------------------
    # Summary statistics
    # ------------------------------------------------------------------
    if matched > 0:
        mae = np.mean(abs_errors)
        rmse = np.sqrt(np.mean(np.array(abs_errors) ** 2))
        avg_ll = np.mean(log_losses)
        print(
            f"\nSummary ({matched} fixtures with market odds):\n"
            f"  Mean absolute error (per outcome):  {mae:.3%}\n"
            f"  RMSE (per outcome):                 {rmse:.3%}\n"
            f"  Avg cross-entropy vs market:        {avg_ll:.4f}\n"
        )

        # Implied fair odds comparison
        print(
            f"{'Match':<45}  "
            f"{'Elo  H':>7} {'Elo  D':>7} {'Elo  A':>7}  "
            f"{'Fair H':>7} {'Fair D':>7} {'Fair A':>7}"
        )
        print("-" * 100)

        for fixture in fixtures:
            fid = fixture["id"]
            htid = fixture["home_team_id"]
            atid = fixture["away_team_id"]

            home = teams.get(htid)
            away = teams.get(atid)
            if not home or not away or fid not in odds_map:
                continue

            entry = odds_map[fid]
            outcomes = entry["outcomes"]
            odds_h = find_outcome_price(outcomes, htid, alias_to_id)
            odds_d = outcomes.get("Draw")
            odds_a = find_outcome_price(outcomes, atid, alias_to_id)
            if not all([odds_h, odds_d, odds_a]):
                continue

            mkt_h, mkt_d, mkt_a = devig(odds_h, odds_d, odds_a)

            elo_h, elo_d, elo_a = elo_1x2(
                float(home["current_elo"]),
                float(away["current_elo"]),
                hfa,
                draw_boundary,
            )

            label = f"{home['name']} v {away['name']}"
            print(
                f"{label:<45}  "
                f"{prob_to_odds(elo_h):>7} {prob_to_odds(elo_d):>7} {prob_to_odds(elo_a):>7}  "
                f"{prob_to_odds(mkt_h):>7} {prob_to_odds(mkt_d):>7} {prob_to_odds(mkt_a):>7}"
            )
        print()
    else:
        print("\nNo fixtures had both Elo ratings and market odds to compare.")


if __name__ == "__main__":
    main()
