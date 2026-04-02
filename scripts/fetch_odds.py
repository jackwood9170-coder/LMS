"""
fetch_odds.py
-------------
Fetches all current EPL events and every available market from The Odds API,
then upserts the data into Supabase.

Usage:
  python scripts/fetch_odds.py

Required environment variables (see .env):
  Odds_Api_Key          – The Odds API key
  SUPABASE_URL          – Supabase project URL
  SUPABASE_SERVICE_ROLE_KEY – Service-role key (bypasses RLS for writes)
"""

import os
import sys
import logging
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

ODDS_API_KEY = os.environ["Odds_Api_Key"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

SPORT_KEY = "soccer_epl"
REGIONS = "eu"                # eu region has the best soccer coverage
MARKETS = "h2h,spreads,totals"  # 1X2, handicap, over/under
ODDS_FORMAT = "decimal"

ODDS_API_BASE = "https://api.the-odds-api.com/v4"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Odds API helpers
# ---------------------------------------------------------------------------

def fetch_epl_events() -> list[dict]:
    """Return all upcoming EPL events with odds for every market."""
    url = f"{ODDS_API_BASE}/sports/{SPORT_KEY}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": "iso",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()

    remaining = resp.headers.get("x-requests-remaining", "?")
    used = resp.headers.get("x-requests-used", "?")
    log.info("Odds API – requests used: %s  remaining: %s", used, remaining)

    return resp.json()


# ---------------------------------------------------------------------------
# Supabase upsert helpers
# ---------------------------------------------------------------------------

def upsert_team(sb: Client, name: str) -> str:
    """Upsert a team by name and return its uuid."""
    result = (
        sb.table("teams")
        .upsert({"name": name}, on_conflict="name")
        .execute()
    )
    return result.data[0]["id"]


def upsert_fixture(sb: Client, event: dict, home_id: str, away_id: str) -> str:
    """Upsert a fixture keyed on odds_api_event_id and return its uuid."""
    payload = {
        "odds_api_event_id": event["id"],
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_team_name": event["home_team"],
        "away_team_name": event["away_team"],
        "kickoff": event["commence_time"],
        "status": "scheduled",
        "has_odds": True,
        # gameweek intentionally NULL — not provided by the Odds API
    }
    result = (
        sb.table("fixtures")
        .upsert(payload, on_conflict="home_team_id,away_team_id")
        .execute()
    )
    return result.data[0]["id"]


def upsert_market_odds(sb: Client, fixture_id: str, event: dict) -> int:
    """Build and upsert every bookmaker × market × outcome row."""
    rows: list[dict] = []
    captured_at = datetime.now(timezone.utc).isoformat()

    for bookmaker in event.get("bookmakers", []):
        bk_key = bookmaker["key"]
        bk_title = bookmaker["title"]

        for market in bookmaker.get("markets", []):
            mk_key = market["key"]
            last_update = market.get("last_update")

            for outcome in market.get("outcomes", []):
                rows.append(
                    {
                        "fixture_id": fixture_id,
                        "bookmaker_key": bk_key,
                        "bookmaker_title": bk_title,
                        "market_key": mk_key,
                        "outcome_name": outcome["name"],
                        "outcome_price": outcome["price"],
                        "outcome_point": outcome.get("point"),  # spreads/totals only
                        "last_update": last_update,
                        "captured_at": captured_at,
                    }
                )

    if not rows:
        return 0

    # Upsert in chunks to stay within Supabase's request size limits
    chunk_size = 500
    total = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        sb.table("market_odds").upsert(
            chunk,
            on_conflict="fixture_id,bookmaker_key,market_key,outcome_name",
        ).execute()
        total += len(chunk)

    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("Connecting to Supabase: %s", SUPABASE_URL)
    sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    log.info("Fetching EPL events from The Odds API …")
    events = fetch_epl_events()
    log.info("Retrieved %d events", len(events))

    if not events:
        log.warning("No events returned – nothing to store.")
        sys.exit(0)

    total_odds_rows = 0

    for event in events:
        home = event["home_team"]
        away = event["away_team"]
        log.info("Processing: %s vs %s  [%s]", home, away, event["commence_time"])

        home_id = upsert_team(sb, home)
        away_id = upsert_team(sb, away)
        fixture_id = upsert_fixture(sb, event, home_id, away_id)

        n = upsert_market_odds(sb, fixture_id, event)
        log.info("  → %d odds rows upserted", n)
        total_odds_rows += n

    log.info("Done. %d total odds rows upserted across %d fixtures.", total_odds_rows, len(events))


if __name__ == "__main__":
    main()
