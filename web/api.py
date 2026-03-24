"""
api.py
------
Lightweight Flask JSON API serving Elo-vs-market comparison data for
upcoming EPL fixtures.

Endpoints:
  GET /api/fixtures  — returns fixture comparison data as JSON

Designed to be consumed by any frontend (static HTML now, Lovable/React later).

Usage:
  python web/api.py

Required environment variables (see .env):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
"""

import os
import sys
from datetime import datetime, timezone
from flask import Flask, jsonify
from dotenv import load_dotenv
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

ELO_SCALE = 400.0

BOOKMAKER_PRIORITY = [
    "pinnacle", "pinnacle_closing",
    "bet365", "bet365_closing",
]

# ---------------------------------------------------------------------------
# Elo 1X2 model (mirrors calibrate_elo.py)
# ---------------------------------------------------------------------------

def elo_1x2(
    rating_home: float, rating_away: float, hfa: float, draw_boundary: float,
) -> tuple[float, float, float]:
    dr = rating_home + hfa - rating_away
    p_home = 1.0 / (1.0 + 10.0 ** (-(dr - draw_boundary) / ELO_SCALE))
    p_away = 1.0 / (1.0 + 10.0 ** ((dr + draw_boundary) / ELO_SCALE))
    p_draw = 1.0 - p_home - p_away
    return p_home, p_draw, p_away


def devig(odds_h: float, odds_d: float, odds_a: float) -> tuple[float, float, float]:
    inv_h, inv_d, inv_a = 1.0 / odds_h, 1.0 / odds_d, 1.0 / odds_a
    overround = inv_h + inv_d + inv_a
    return inv_h / overround, inv_d / overround, inv_a / overround


# ---------------------------------------------------------------------------
# Team name aliases
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
    name_to_id = {name: tid for tid, name in teams_map.items()}
    alias_to_id: dict[str, str] = dict(name_to_id)
    for alias, canonical in _ALIASES.items():
        if canonical in name_to_id and alias not in alias_to_id:
            alias_to_id[alias] = name_to_id[canonical]
    return alias_to_id


def find_outcome_price(
    outcomes: dict[str, float], team_id: str, alias_to_id: dict[str, str],
) -> float | None:
    for outcome_name, price in outcomes.items():
        if alias_to_id.get(outcome_name) == team_id:
            return price
    return None


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def load_teams(sb: Client) -> dict[str, dict]:
    result = sb.table("teams").select("id, name, current_elo").execute()
    return {r["id"]: r for r in result.data}


def load_model_params(sb: Client) -> dict[str, float]:
    result = sb.table("model_params").select("key, value").execute()
    return {r["key"]: float(r["value"]) for r in result.data}


def load_upcoming_fixtures(sb: Client) -> list[dict]:
    """Load only future scheduled fixtures (kickoff after now)."""
    now = datetime.now(timezone.utc).isoformat()
    result = (
        sb.table("fixtures")
        .select("id, home_team_id, away_team_id, kickoff, gameweek")
        .eq("status", "scheduled")
        .gt("kickoff", now)
        .order("kickoff")
        .execute()
    )
    return result.data


def load_h2h_odds_pinbet(sb: Client, fixture_ids: list[str]) -> dict[str, dict]:
    """
    Only return fixtures that have Pinnacle or Bet365 h2h odds.
    No average fallback — UI requirement.
    """
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

    raw: dict[str, dict[str, dict[str, float]]] = {}
    for row in all_rows:
        fid = row["fixture_id"]
        bk = row["bookmaker_key"]
        raw.setdefault(fid, {}).setdefault(bk, {})[row["outcome_name"]] = float(
            row["outcome_price"]
        )

    best: dict[str, dict] = {}
    for fid, bk_map in raw.items():
        for bk in BOOKMAKER_PRIORITY:
            outcomes = bk_map.get(bk, {})
            if len(outcomes) == 3:
                best[fid] = {"outcomes": outcomes, "source": bk}
                break

    return best


# ---------------------------------------------------------------------------
# Build comparison payload
# ---------------------------------------------------------------------------

def build_comparison_data() -> dict:
    sb = get_supabase()

    params = load_model_params(sb)
    hfa = params.get("hfa")
    draw_boundary = params.get("draw_boundary")
    if hfa is None or draw_boundary is None:
        return {"error": "Model not calibrated. Run calibrate_elo.py first.", "fixtures": []}

    teams = load_teams(sb)
    alias_to_id = build_alias_map({tid: t["name"] for tid, t in teams.items()})

    fixtures = load_upcoming_fixtures(sb)
    if not fixtures:
        return {"fixtures": [], "model": {"hfa": hfa, "draw_boundary": draw_boundary}}

    fixture_ids = [f["id"] for f in fixtures]
    odds_map = load_h2h_odds_pinbet(sb, fixture_ids)

    rows = []
    for fixture in fixtures:
        fid = fixture["id"]
        htid = fixture["home_team_id"]
        atid = fixture["away_team_id"]

        home = teams.get(htid)
        away = teams.get(atid)
        if not home or not away:
            continue
        if fid not in odds_map:
            continue

        entry = odds_map[fid]
        outcomes = entry["outcomes"]
        source = entry["source"]

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

        rows.append({
            "home_team": home["name"],
            "away_team": away["name"],
            "home_elo": round(float(home["current_elo"]), 1),
            "away_elo": round(float(away["current_elo"]), 1),
            "kickoff": fixture["kickoff"],
            "gameweek": fixture.get("gameweek"),
            "source": source,
            "market": {
                "home": round(mkt_h * 100, 1),
                "draw": round(mkt_d * 100, 1),
                "away": round(mkt_a * 100, 1),
            },
            "model": {
                "home": round(elo_h * 100, 1),
                "draw": round(elo_d * 100, 1),
                "away": round(elo_a * 100, 1),
            },
            "diff": {
                "home": round((elo_h - mkt_h) * 100, 1),
                "draw": round((elo_d - mkt_d) * 100, 1),
                "away": round((elo_a - mkt_a) * 100, 1),
            },
        })

    return {
        "fixtures": rows,
        "model": {"hfa": round(hfa, 1), "draw_boundary": round(draw_boundary, 1)},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="static")


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/fixtures")
def api_fixtures():
    data = build_comparison_data()
    return jsonify(data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
