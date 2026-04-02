"""
lms_solver.py
-------------
Last-Man-Standing solver.

Given:
  - Elo ratings + model params (HFA, draw boundary)
  - Remaining fixtures per gameweek
  - Teams already used
  - Historical game durations for horizon estimation

Produces an optimal sequence of team picks that maximises the probability
of surviving all remaining gameweeks in the planning horizon.

Algorithm:
  For N remaining gameweeks with M available teams, we solve a sequential
  assignment problem via dynamic programming over a bitmask of used teams.
  When M ≤ 20 and N ≤ ~10 this is fast enough.  For larger horizons we
  fall back to a greedy heuristic with look-ahead.

Historical durations [1, 5, 3, 10] → fitted to a geometric distribution
gives p_elim ≈ 0.21 per round, so the expected remaining rounds from any
point is ~4.75.  We plan over `ceil(expected_remaining)` gameweeks.
"""

from __future__ import annotations

import math
import logging
from itertools import combinations
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

ELO_SCALE = 400.0

# Historical game durations from the user's LMS group
HISTORICAL_DURATIONS = [1, 5, 3, 10]


# ---------------------------------------------------------------------------
# Elo model (copied to keep this module self-contained)
# ---------------------------------------------------------------------------

def elo_win_prob(
    rating_home: float,
    rating_away: float,
    hfa: float,
    draw_boundary: float,
    is_home: bool,
) -> float:
    """Return P(win) for the team of interest."""
    dr = rating_home + hfa - rating_away
    p_home = 1.0 / (1.0 + 10.0 ** (-(dr - draw_boundary) / ELO_SCALE))
    p_away = 1.0 / (1.0 + 10.0 ** ((dr + draw_boundary) / ELO_SCALE))
    return p_home if is_home else p_away


# ---------------------------------------------------------------------------
# Horizon estimation
# ---------------------------------------------------------------------------

def estimate_horizon(
    durations: list[int] = HISTORICAL_DURATIONS,
    current_week_in_game: int = 1,
) -> int:
    """
    Estimate how many MORE gameweeks the current LMS game is likely to last.

    Model: each round, every remaining player has an independent probability
    p_elim of being eliminated.  The game ends when only one survives from
    an initial field.  We approximate the *individual* game length as
    geometric(p_elim).

    MLE for geometric distribution: p_hat = 1 / mean(durations)
    Expected total duration = 1 / p_hat = mean(durations)
    Remaining = max(1, round(mean - weeks_already_played))

    We also cap at the number of gameweeks left in the season.
    """
    mean_dur = sum(durations) / len(durations)
    # Variance tells us something about uncertainty — use upper end
    var_dur = sum((d - mean_dur) ** 2 for d in durations) / len(durations)
    std_dur = math.sqrt(var_dur)
    # Plan for mean + 0.5*std to be somewhat conservative
    target = mean_dur + 0.5 * std_dur
    remaining = max(1, round(target - (current_week_in_game - 1)))
    return remaining


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MatchOption:
    """One fixture where a team can be picked."""
    team_id: str
    team_name: str
    opponent_id: str
    opponent_name: str
    is_home: bool
    win_prob: float  # P(win) used by solver (market if available, else model)
    team_elo: float
    opponent_elo: float
    source: str = "model"  # "market" or "model"


@dataclass
class GameweekSlot:
    """All available pick options for one gameweek."""
    gameweek: int
    options: list[MatchOption] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Build gameweek options
# ---------------------------------------------------------------------------

def build_gameweek_options(
    fixtures: list[dict],
    teams: dict[str, dict],
    hfa: float,
    draw_boundary: float,
    used_team_ids: set[str],
    included_gws: set[int] | None = None,
    market_win_probs: dict[str, dict[str, float]] | None = None,
) -> list[GameweekSlot]:
    """
    Build available pick options per gameweek.

    fixtures: list of {home_team_id, away_team_id, gameweek, kickoff, id, ...}
    teams: {team_id: {name, current_elo}}
    used_team_ids: teams already picked in this LMS game
    included_gws: if provided, only include these gameweeks
    market_win_probs: {fixture_id: {"home": p_home, "away": p_away}} — de-vigged
                      market probs.  Used as truth when available.
    """
    if market_win_probs is None:
        market_win_probs = {}

    gw_map: dict[int, list[dict]] = {}
    for f in fixtures:
        gw = f.get("gameweek")
        if gw is None:
            continue
        if included_gws is not None and gw not in included_gws:
            continue
        gw_map.setdefault(gw, []).append(f)

    slots: list[GameweekSlot] = []
    for gw in sorted(gw_map.keys()):
        slot = GameweekSlot(gameweek=gw)
        for f in gw_map[gw]:
            htid = f["home_team_id"]
            atid = f["away_team_id"]
            fid = f.get("id")
            home = teams.get(htid)
            away = teams.get(atid)
            if not home or not away:
                continue

            h_elo = float(home["current_elo"])
            a_elo = float(away["current_elo"])

            # Prefer market odds when available
            mkt = market_win_probs.get(fid) if fid else None

            # Home team option
            if htid not in used_team_ids:
                if mkt and "home" in mkt:
                    wp = mkt["home"]
                    src = "market"
                else:
                    wp = elo_win_prob(h_elo, a_elo, hfa, draw_boundary, is_home=True)
                    src = "model"
                slot.options.append(MatchOption(
                    team_id=htid, team_name=home["name"],
                    opponent_id=atid, opponent_name=away["name"],
                    is_home=True, win_prob=wp,
                    team_elo=h_elo, opponent_elo=a_elo,
                    source=src,
                ))

            # Away team option
            if atid not in used_team_ids:
                if mkt and "away" in mkt:
                    wp = mkt["away"]
                    src = "market"
                else:
                    wp = elo_win_prob(h_elo, a_elo, hfa, draw_boundary, is_home=False)
                    src = "model"
                slot.options.append(MatchOption(
                    team_id=atid, team_name=away["name"],
                    opponent_id=htid, opponent_name=home["name"],
                    is_home=False, win_prob=wp,
                    team_elo=a_elo, opponent_elo=h_elo,
                    source=src,
                ))

        if slot.options:
            slots.append(slot)

    return slots


# ---------------------------------------------------------------------------
# DP solver
# ---------------------------------------------------------------------------

def solve_dp(
    slots: list[GameweekSlot],
    horizon: int,
) -> tuple[float, list[MatchOption | None]]:
    """
    Solve the LMS pick sequence via DP.

    Returns (survival_probability, [pick_for_gw_0, pick_for_gw_1, ...]).
    Only plans over min(horizon, len(slots)) gameweeks.
    """
    n = min(horizon, len(slots))
    if n == 0:
        return 1.0, []

    slots = slots[:n]

    # Build team index for bitmask (only teams appearing in the slots)
    all_team_ids: list[str] = []
    tid_set: set[str] = set()
    for s in slots:
        for opt in s.options:
            if opt.team_id not in tid_set:
                tid_set.add(opt.team_id)
                all_team_ids.append(opt.team_id)

    if len(all_team_ids) > 22:
        # Too many teams for bitmask DP — use greedy
        return solve_greedy(slots, horizon)

    tid_to_bit = {tid: 1 << i for i, tid in enumerate(all_team_ids)}

    # dp[mask] = best survival probability using exactly the teams in mask
    # We process gameweeks in order, one pick per gameweek.
    # State: (gameweek_index, used_mask) → (best_prob, best_pick_chain)

    # Forward DP
    # dp[gw][mask] = max survival prob from gw onwards given mask already used
    INF_MEMO: dict[tuple[int, int], tuple[float, list]] = {}

    def dp(gw_idx: int, mask: int) -> tuple[float, list]:
        if gw_idx == n:
            return 1.0, []
        key = (gw_idx, mask)
        if key in INF_MEMO:
            return INF_MEMO[key]

        best_prob = 0.0
        best_seq: list = []
        slot = slots[gw_idx]

        for opt in slot.options:
            bit = tid_to_bit.get(opt.team_id, 0)
            if mask & bit:
                continue  # already used
            future_prob, future_seq = dp(gw_idx + 1, mask | bit)
            total = opt.win_prob * future_prob
            if total > best_prob:
                best_prob = total
                best_seq = [opt] + future_seq

        # Also consider "no good pick" — skip this GW (prob=0 survival
        # if we must pick, but we always must in LMS)
        if best_prob == 0.0:
            # No available team — forced elimination
            best_seq = [None] * (n - gw_idx)

        INF_MEMO[key] = (best_prob, best_seq)
        return best_prob, best_seq

    prob, seq = dp(0, 0)
    return prob, seq


def solve_greedy(
    slots: list[GameweekSlot],
    horizon: int,
) -> tuple[float, list[MatchOption | None]]:
    """
    Greedy with 1-step lookahead fallback for large team sets.
    At each gameweek, pick the team giving the best
    (this_week_prob * best_available_next_week_prob).
    """
    n = min(horizon, len(slots))
    used: set[str] = set()
    picks: list[MatchOption | None] = []
    total_prob = 1.0

    for i in range(n):
        slot = slots[i]
        available = [o for o in slot.options if o.team_id not in used]

        if not available:
            picks.append(None)
            total_prob = 0.0
            continue

        if i + 1 < n:
            # 1-step lookahead
            next_slot = slots[i + 1]
            best_score = 0.0
            best_opt = available[0]
            for opt in available:
                # What's the best next-week prob if we use this team now?
                next_available = [
                    o for o in next_slot.options
                    if o.team_id not in used and o.team_id != opt.team_id
                ]
                next_best = max((o.win_prob for o in next_available), default=0)
                score = opt.win_prob * next_best
                if score > best_score:
                    best_score = score
                    best_opt = opt
        else:
            best_opt = max(available, key=lambda o: o.win_prob)

        picks.append(best_opt)
        used.add(best_opt.team_id)
        total_prob *= best_opt.win_prob

    return total_prob, picks


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------

@dataclass
class LMSRecommendation:
    """Full solver output."""
    current_gw: int
    horizon: int
    expected_duration: float
    survival_prob: float
    picks: list[dict]  # [{gameweek, team_name, opponent_name, is_home, win_prob, ...}]
    all_options: list[dict]  # all options for current GW ranked


def recommend(
    fixtures: list[dict],
    teams: dict[str, dict],
    hfa: float,
    draw_boundary: float,
    used_team_ids: set[str],
    current_week_in_game: int = 1,
    included_gws: set[int] | None = None,
    durations: list[int] = HISTORICAL_DURATIONS,
    market_win_probs: dict[str, dict[str, float]] | None = None,
) -> LMSRecommendation:
    """
    Run the full LMS solver and return a recommendation.

    market_win_probs: {fixture_id: {"home": p, "away": p}} de-vigged market
                      probabilities.  Used as the source of truth when present;
                      model probabilities are the fallback.
    """
    horizon = estimate_horizon(durations, current_week_in_game)
    log.info("LMS horizon: %d gameweeks (week %d of game)", horizon, current_week_in_game)

    slots = build_gameweek_options(
        fixtures, teams, hfa, draw_boundary, used_team_ids, included_gws,
        market_win_probs=market_win_probs,
    )

    if not slots:
        return LMSRecommendation(
            current_gw=0, horizon=horizon,
            expected_duration=sum(durations) / len(durations),
            survival_prob=0.0, picks=[], all_options=[],
        )

    current_gw = slots[0].gameweek
    survival_prob, pick_seq = solve_dp(slots, horizon)

    picks_out = []
    for i, pick in enumerate(pick_seq):
        gw = slots[i].gameweek if i < len(slots) else None
        if pick is None:
            picks_out.append({"gameweek": gw, "team_name": None, "win_prob": 0})
            continue
        picks_out.append({
            "gameweek": gw,
            "team_id": pick.team_id,
            "team_name": pick.team_name,
            "opponent_name": pick.opponent_name,
            "is_home": pick.is_home,
            "win_prob": round(pick.win_prob * 100, 1),
            "team_elo": pick.team_elo,
            "opponent_elo": pick.opponent_elo,
            "source": pick.source,
        })

    # All options for current GW, ranked
    all_opts = sorted(slots[0].options, key=lambda o: o.win_prob, reverse=True)
    all_options_out = [{
        "team_id": o.team_id,
        "team_name": o.team_name,
        "opponent_name": o.opponent_name,
        "is_home": o.is_home,
        "win_prob": round(o.win_prob * 100, 1),
        "team_elo": o.team_elo,
        "opponent_elo": o.opponent_elo,
        "source": o.source,
    } for o in all_opts]

    mean_dur = sum(durations) / len(durations)

    return LMSRecommendation(
        current_gw=current_gw,
        horizon=horizon,
        expected_duration=round(mean_dur, 1),
        survival_prob=round(survival_prob * 100, 2),
        picks=picks_out,
        all_options=all_options_out,
    )
