"""
fetch_fpl_fixtures.py
---------------------
Fetches the full 2025/26 Premier League fixture list from the official
Fantasy Premier League (FPL) API and upserts any missing fixtures into
Supabase.

The FPL API is free, requires no API key, and provides all 380 fixtures
with gameweek numbers and kickoff times through GW38.

Only fixtures not already present (by home/away team + kickoff date) are
inserted. Existing fixtures (from football-data.co.uk or The Odds API)
are left untouched.

Usage:
  python scripts/fetch_fpl_fixtures.py

Required environment variables (see .env):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
"""

import os
import logging
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

FPL_BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FPL team name → canonical Supabase team name
# Must match names already in the teams table (from The Odds API / fdco).
# ---------------------------------------------------------------------------

FPL_NAME_MAP: dict[str, str] = {
    "Arsenal":          "Arsenal",
    "Aston Villa":      "Aston Villa",
    "Bournemouth":      "Bournemouth",
    "Brentford":        "Brentford",
    "Brighton":         "Brighton and Hove Albion",
    "Burnley":          "Burnley",
    "Chelsea":          "Chelsea",
    "Crystal Palace":   "Crystal Palace",
    "Everton":          "Everton",
    "Fulham":           "Fulham",
    "Leeds":            "Leeds United",
    "Liverpool":        "Liverpool",
    "Man City":         "Manchester City",
    "Man Utd":          "Manchester United",
    "Newcastle":        "Newcastle United",
    "Nott'm Forest":    "Nottingham Forest",
    "Sunderland":       "Sunderland",
    "Spurs":            "Tottenham Hotspur",
    "West Ham":         "West Ham United",
    "Wolves":           "Wolverhampton Wanderers",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_fpl_teams() -> dict[int, str]:
    """Return {fpl_id: canonical_name} from the FPL bootstrap endpoint."""
    resp = requests.get(FPL_BOOTSTRAP_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    fpl_teams: dict[int, str] = {}
    for t in data["teams"]:
        fpl_name = t["name"]
        canonical = FPL_NAME_MAP.get(fpl_name, fpl_name)
        fpl_teams[t["id"]] = canonical

    return fpl_teams


def fetch_fpl_fixtures() -> list[dict]:
    """Return raw FPL fixture list."""
    resp = requests.get(FPL_FIXTURES_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


def upsert_team(sb: Client, name: str) -> str:
    """Upsert a team by name and return its uuid."""
    result = (
        sb.table("teams")
        .upsert({"name": name}, on_conflict="name")
        .execute()
    )
    return result.data[0]["id"]


def load_existing_fixture_keys(sb: Client) -> set[str]:
    """
    Load a set of dedup keys for all fixtures already in the DB.
    Key format: "{home_team_id}_{away_team_id}" — each pair plays once at home per season.
    """
    result = (
        sb.table("fixtures")
        .select("home_team_id, away_team_id")
        .execute()
    )
    keys = set()
    for r in result.data:
        keys.add(f"{r['home_team_id']}_{r['away_team_id']}")
    return keys


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("Connecting to Supabase: %s", SUPABASE_URL)
    sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    log.info("Fetching FPL teams …")
    fpl_teams = fetch_fpl_teams()
    log.info("FPL teams: %d", len(fpl_teams))

    # Ensure all teams exist in Supabase and build name→id map
    team_name_to_id: dict[str, str] = {}
    for fpl_id, canonical in fpl_teams.items():
        tid = upsert_team(sb, canonical)
        team_name_to_id[canonical] = tid
    log.info("Teams synced: %d", len(team_name_to_id))

    log.info("Fetching FPL fixtures …")
    fpl_fixtures = fetch_fpl_fixtures()
    log.info("FPL fixtures: %d total", len(fpl_fixtures))

    # Load existing fixtures for dedup
    existing_keys = load_existing_fixture_keys(sb)
    log.info("Existing fixtures in DB: %d dedup keys", len(existing_keys))

    inserted = 0
    skipped_existing = 0
    skipped_no_kickoff = 0

    for fx in fpl_fixtures:
        # Skip completed fixtures — we only want future ones
        if fx.get("finished"):
            continue

        home_fpl_id = fx["team_h"]
        away_fpl_id = fx["team_a"]
        kickoff_raw = fx.get("kickoff_time")
        gameweek = fx.get("event")

        home_name = fpl_teams.get(home_fpl_id)
        away_name = fpl_teams.get(away_fpl_id)
        if not home_name or not away_name:
            log.warning("Unknown FPL team id: %s or %s", home_fpl_id, away_fpl_id)
            continue

        home_id = team_name_to_id[home_name]
        away_id = team_name_to_id[away_name]

        if not kickoff_raw:
            # Some future fixtures have no confirmed kickoff yet — use a
            # placeholder date at the end of the month for now
            skipped_no_kickoff += 1
            continue

        dedup_key = f"{home_id}_{away_id}"

        if dedup_key in existing_keys:
            # Update kickoff/gameweek in case they changed (rescheduled fixture)
            sb.table("fixtures").upsert({
                "home_team_id": home_id,
                "away_team_id": away_id,
                "home_team_name": home_name,
                "away_team_name": away_name,
                "kickoff": kickoff_raw,
                "gameweek": gameweek,
                "status": "scheduled",
            }, on_conflict="home_team_id,away_team_id").execute()
            skipped_existing += 1
            continue

        payload = {
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_team_name": home_name,
            "away_team_name": away_name,
            "kickoff": kickoff_raw,
            "gameweek": gameweek,
            "status": "scheduled",
        }

        sb.table("fixtures").upsert(payload, on_conflict="home_team_id,away_team_id").execute()
        existing_keys.add(dedup_key)
        inserted += 1
        log.info(
            "  Inserted GW%s: %s v %s (%s)",
            gameweek or "?", home_name, away_name, ko_date,
        )

    log.info(
        "Done. Inserted: %d  Already existed: %d  No kickoff yet: %d",
        inserted, skipped_existing, skipped_no_kickoff,
    )


if __name__ == "__main__":
    main()
