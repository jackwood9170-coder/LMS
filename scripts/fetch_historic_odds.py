"""
fetch_historic_odds.py
----------------------
Downloads the current 2025/26 Premier League season CSV from football-data.co.uk
and upserts:
  - teams
  - fixtures  (with full-time and half-time results)
  - market_odds  (closing h2h, totals, spreads from Bet365, Pinnacle, Max, Avg)

Only rows with a completed result (FTR column populated) are processed.
Closing odds are used — they reflect the final market consensus before kickoff
and are the most useful for reverse-engineering ELO ratings.

Usage:
  python scripts/fetch_historic_odds.py

Required environment variables (see .env):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
"""

import os
import io
import csv
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

# Current 2025/26 EPL season CSV.  Update the season prefix (2526) each summer.
FDCO_URL = "https://www.football-data.co.uk/mmz4281/2526/E0.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Team name normalisation
# football-data.co.uk uses shortened names; map them to the canonical names
# that The Odds API (and therefore our teams table) uses.
# ---------------------------------------------------------------------------

TEAM_NAME_MAP: dict[str, str] = {
    "Man United":     "Manchester United",
    "Man City":       "Manchester City",
    "Brighton":       "Brighton and Hove Albion",
    "Nott'm Forest":  "Nottingham Forest",
    "Newcastle":      "Newcastle United",
    "West Ham":       "West Ham United",
    "Wolves":         "Wolverhampton Wanderers",
    "Spurs":          "Tottenham Hotspur",
    "Tottenham":      "Tottenham Hotspur",
    "Leeds":          "Leeds United",
    "Leicester":      "Leicester City",
    "Norwich":        "Norwich City",
    "Ipswich":        "Ipswich Town",
    "Sheffield United": "Sheffield United",
    "Sheffield Weds": "Sheffield Wednesday",
    "QPR":            "Queens Park Rangers",
    "Huddersfield":   "Huddersfield Town",
    "Cardiff":        "Cardiff City",
    "Stoke":          "Stoke City",
    "Swansea":        "Swansea City",
    "Coventry":       "Coventry City",
}


def normalize_team(name: str) -> str:
    return TEAM_NAME_MAP.get(name.strip(), name.strip())


# ---------------------------------------------------------------------------
# Odds extraction helpers
# ---------------------------------------------------------------------------

def _safe_float(val: str | None) -> float | None:
    """Return a positive float or None (treats 0 / blank / non-numeric as None)."""
    try:
        f = float(val)  # type: ignore[arg-type]
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _safe_int(val: str | None) -> int | None:
    try:
        return int(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def build_odds_rows(
    row: dict,
    fixture_id: str,
    home_team: str,
    away_team: str,
    captured_at: str,
) -> list[dict]:
    """
    Build market_odds rows from closing-price columns.

    Markets stored:
      h2h     — 1X2, bookmakers: Bet365, Pinnacle, Market Max, Market Avg
      totals  — Over/Under 2.5, bookmakers: Bet365, Market Max, Market Avg
      spreads — Asian handicap, bookmakers: Bet365, Market Max, Market Avg
    """
    odds_rows: list[dict] = []

    # -- 1X2 / h2h --------------------------------------------------------
    h2h_books = [
        ("bet365_closing",   "Bet365 (Closing)",  "B365CH", "B365CD", "B365CA"),
        ("pinnacle_closing", "Pinnacle (Closing)", "PSCH",   "PSCD",   "PSCA"),
        ("market_max",       "Market Maximum",     "MaxCH",  "MaxCD",  "MaxCA"),
        ("market_avg",       "Market Average",     "AvgCH",  "AvgCD",  "AvgCA"),
    ]
    for bk_key, bk_title, col_h, col_d, col_a in h2h_books:
        for outcome_name, col in ((home_team, col_h), ("Draw", col_d), (away_team, col_a)):
            price = _safe_float(row.get(col))
            if price is not None:
                odds_rows.append({
                    "fixture_id":     fixture_id,
                    "bookmaker_key":  bk_key,
                    "bookmaker_title": bk_title,
                    "market_key":     "h2h",
                    "outcome_name":   outcome_name,
                    "outcome_price":  price,
                    "outcome_point":  None,
                    "last_update":    None,
                    "captured_at":    captured_at,
                })

    # -- Totals (Over/Under 2.5) ------------------------------------------
    totals_books = [
        ("bet365_closing", "Bet365 (Closing)", "B365C>2.5", "B365C<2.5"),
        ("market_max",     "Market Maximum",   "MaxC>2.5",  "MaxC<2.5"),
        ("market_avg",     "Market Average",   "AvgC>2.5",  "AvgC<2.5"),
    ]
    for bk_key, bk_title, col_over, col_under in totals_books:
        for outcome_name, col in (("Over", col_over), ("Under", col_under)):
            price = _safe_float(row.get(col))
            if price is not None:
                odds_rows.append({
                    "fixture_id":     fixture_id,
                    "bookmaker_key":  bk_key,
                    "bookmaker_title": bk_title,
                    "market_key":     "totals",
                    "outcome_name":   outcome_name,
                    "outcome_price":  price,
                    "outcome_point":  2.5,
                    "last_update":    None,
                    "captured_at":    captured_at,
                })

    # -- Spreads / Asian Handicap -----------------------------------------
    ah_line = _safe_float(row.get("AHCh"))
    if ah_line is not None:
        ah_books = [
            ("bet365_closing", "Bet365 (Closing)", "B365CAHH", "B365CAHA"),
            ("market_max",     "Market Maximum",   "MaxCAHH",  "MaxCAHA"),
            ("market_avg",     "Market Average",   "AvgCAHH",  "AvgCAHA"),
        ]
        for bk_key, bk_title, col_home, col_away in ah_books:
            for outcome_name, col, point in (
                (home_team, col_home,  ah_line),
                (away_team, col_away, -ah_line),
            ):
                price = _safe_float(row.get(col))
                if price is not None:
                    odds_rows.append({
                        "fixture_id":     fixture_id,
                        "bookmaker_key":  bk_key,
                        "bookmaker_title": bk_title,
                        "market_key":     "spreads",
                        "outcome_name":   outcome_name,
                        "outcome_price":  price,
                        "outcome_point":  point,
                        "last_update":    None,
                        "captured_at":    captured_at,
                    })

    return odds_rows


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def upsert_team(sb: Client, name: str) -> str:
    result = (
        sb.table("teams")
        .upsert({"name": name}, on_conflict="name")
        .execute()
    )
    return result.data[0]["id"]


def upsert_fixture(sb: Client, payload: dict) -> str:
    result = (
        sb.table("fixtures")
        .upsert(payload, on_conflict="fdco_match_key")
        .execute()
    )
    return result.data[0]["id"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("Connecting to Supabase: %s", SUPABASE_URL)
    sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    log.info("Downloading CSV: %s", FDCO_URL)
    resp = requests.get(FDCO_URL, timeout=30)
    resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))
    # Only process rows where the match has been played (FTR is populated)
    all_rows = [r for r in reader if r.get("FTR", "").strip() in ("H", "D", "A")]
    log.info("Found %d completed fixtures in CSV", len(all_rows))

    total_odds_rows = 0

    for row in all_rows:
        home = normalize_team(row["HomeTeam"])
        away = normalize_team(row["AwayTeam"])
        date_str = row["Date"].strip()          # DD/MM/YYYY
        time_str = row.get("Time", "").strip() or "15:00"

        # Parse kickoff — football-data uses local UK time; store as UTC
        # (close enough for historical analysis; exact TZ offset not critical)
        kickoff_dt = datetime.strptime(
            f"{date_str} {time_str}", "%d/%m/%Y %H:%M"
        ).replace(tzinfo=timezone.utc)
        kickoff_iso = kickoff_dt.isoformat()

        # Dedup key: stable identifier independent of any external API
        fdco_key = f"{home}_{away}_{date_str}"

        home_id = upsert_team(sb, home)
        away_id = upsert_team(sb, away)

        fixture_payload = {
            "fdco_match_key": fdco_key,
            "home_team_id":   home_id,
            "away_team_id":   away_id,
            "kickoff":        kickoff_iso,
            "status":         "completed",
            "home_goals":     _safe_int(row.get("FTHG")),
            "away_goals":     _safe_int(row.get("FTAG")),
            "result":         row.get("FTR", "").strip() or None,
            "ht_home_goals":  _safe_int(row.get("HTHG")),
            "ht_away_goals":  _safe_int(row.get("HTAG")),
            # gameweek intentionally omitted — not in this data source
        }

        fixture_id = upsert_fixture(sb, fixture_payload)

        captured_at = datetime.now(timezone.utc).isoformat()
        odds_rows = build_odds_rows(row, fixture_id, home, away, captured_at)

        if odds_rows:
            chunk_size = 500
            for i in range(0, len(odds_rows), chunk_size):
                sb.table("market_odds").upsert(
                    odds_rows[i : i + chunk_size],
                    on_conflict="fixture_id,bookmaker_key,market_key,outcome_name",
                ).execute()

        total_odds_rows += len(odds_rows)
        log.info(
            "  %s %d-%d %s  [%s]  → %d odds rows",
            home,
            _safe_int(row.get("FTHG")) or 0,
            _safe_int(row.get("FTAG")) or 0,
            away,
            row.get("FTR"),
            len(odds_rows),
        )

    log.info(
        "Done. %d total odds rows upserted across %d completed fixtures.",
        total_odds_rows,
        len(all_rows),
    )


if __name__ == "__main__":
    main()
