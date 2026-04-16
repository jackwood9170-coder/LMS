import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
}

const ELO_SCALE = 400
const HISTORICAL_DURATIONS = [1, 5, 3, 10]
const BOOKMAKER_PRIORITY = [
  "pinnacle",
  "pinnacle_closing",
  "bet365",
  "bet365_closing",
]

// ---- Team name aliases ----

const ALIASES: Record<string, string> = {
  "Man United": "Manchester United",
  "Man City": "Manchester City",
  "Brighton": "Brighton and Hove Albion",
  "Nott'm Forest": "Nottingham Forest",
  "Newcastle": "Newcastle United",
  "West Ham": "West Ham United",
  "Wolves": "Wolverhampton Wanderers",
  "Spurs": "Tottenham Hotspur",
  "Tottenham": "Tottenham Hotspur",
  "Leeds": "Leeds United",
  "Leicester": "Leicester City",
  "Norwich": "Norwich City",
  "Ipswich": "Ipswich Town",
  "Sheffield Weds": "Sheffield Wednesday",
  "QPR": "Queens Park Rangers",
  "Huddersfield": "Huddersfield Town",
  "Cardiff": "Cardiff City",
  "Stoke": "Stoke City",
  "Swansea": "Swansea City",
  "Coventry": "Coventry City",
  "Brighton & Hove Albion": "Brighton and Hove Albion",
  "Nottingham Forest": "Nottingham Forest",
  "Wolverhampton": "Wolverhampton Wanderers",
  "Sunderland AFC": "Sunderland",
}

function buildAliasMap(
  teamsMap: Record<string, string>,
): Record<string, string> {
  const nameToId: Record<string, string> = {}
  for (const [tid, name] of Object.entries(teamsMap)) nameToId[name] = tid
  const aliasToId = { ...nameToId }
  for (const [alias, canonical] of Object.entries(ALIASES)) {
    if (canonical in nameToId && !(alias in aliasToId))
      aliasToId[alias] = nameToId[canonical]
  }
  return aliasToId
}

function findOutcomePrice(
  outcomes: Record<string, number>,
  teamId: string,
  aliasToId: Record<string, string>,
): number | null {
  for (const [name, price] of Object.entries(outcomes)) {
    if (aliasToId[name] === teamId) return price
  }
  return null
}

// ---- ELO helpers ----

function eloWinProb(
  rH: number,
  rA: number,
  hfa: number,
  db: number,
  isHome: boolean,
): number {
  const dr = rH + hfa - rA
  const pH = 1 / (1 + Math.pow(10, -(dr - db) / ELO_SCALE))
  const pA = 1 / (1 + Math.pow(10, (dr + db) / ELO_SCALE))
  return isHome ? pH : pA
}

function devig(
  oH: number,
  oD: number,
  oA: number,
): [number, number, number] {
  const iH = 1 / oH,
    iD = 1 / oD,
    iA = 1 / oA
  const s = iH + iD + iA
  return [iH / s, iD / s, iA / s]
}

// ---- Horizon estimation ----

function estimateHorizon(
  durations: number[] = HISTORICAL_DURATIONS,
  currentWeek: number = 1,
): number {
  const mean = durations.reduce((a, b) => a + b, 0) / durations.length
  const variance =
    durations.reduce((a, d) => a + (d - mean) ** 2, 0) / durations.length
  const std = Math.sqrt(variance)
  const target = mean + 0.5 * std
  return Math.max(1, Math.round(target - (currentWeek - 1)))
}

// ---- Solver data structures ----

interface MatchOption {
  teamId: string
  teamName: string
  opponentId: string
  opponentName: string
  isHome: boolean
  winProb: number
  teamElo: number
  opponentElo: number
  source: string
}

interface GWSlot {
  gameweek: number
  options: MatchOption[]
}

// ---- Build gameweek options ----

function buildGWOptions(
  fixtures: any[],
  teams: Record<string, any>,
  hfa: number,
  db: number,
  usedTeamIds: Set<string>,
  includedGWs: Set<number> | null,
  marketWinProbs: Record<string, { home: number; away: number }>,
): GWSlot[] {
  const gwMap: Record<number, any[]> = {}
  for (const f of fixtures) {
    const gw = f.gameweek
    if (gw == null) continue
    if (includedGWs && !includedGWs.has(gw)) continue
    if (!gwMap[gw]) gwMap[gw] = []
    gwMap[gw].push(f)
  }

  const slots: GWSlot[] = []
  for (const gw of Object.keys(gwMap)
    .map(Number)
    .sort((a, b) => a - b)) {
    const slot: GWSlot = { gameweek: gw, options: [] }
    for (const f of gwMap[gw]) {
      const home = teams[f.home_team_id]
      const away = teams[f.away_team_id]
      if (!home || !away) continue

      const hElo = Number(home.current_elo)
      const aElo = Number(away.current_elo)
      const mkt = f.id ? marketWinProbs[f.id] : undefined

      // Home team option
      if (!usedTeamIds.has(f.home_team_id)) {
        const wp =
          mkt?.home ?? eloWinProb(hElo, aElo, hfa, db, true)
        slot.options.push({
          teamId: f.home_team_id,
          teamName: home.name,
          opponentId: f.away_team_id,
          opponentName: away.name,
          isHome: true,
          winProb: wp,
          teamElo: hElo,
          opponentElo: aElo,
          source: mkt?.home != null ? "market" : "model",
        })
      }

      // Away team option
      if (!usedTeamIds.has(f.away_team_id)) {
        const wp =
          mkt?.away ?? eloWinProb(hElo, aElo, hfa, db, false)
        slot.options.push({
          teamId: f.away_team_id,
          teamName: away.name,
          opponentId: f.home_team_id,
          opponentName: home.name,
          isHome: false,
          winProb: wp,
          teamElo: aElo,
          opponentElo: hElo,
          source: mkt?.away != null ? "market" : "model",
        })
      }
    }
    if (slot.options.length > 0) slots.push(slot)
  }
  return slots
}

// ---- DP solver (bitmask memoization) ----

function solveDP(
  slots: GWSlot[],
  horizon: number,
): { prob: number; picks: (MatchOption | null)[] } {
  const n = Math.min(horizon, slots.length)
  if (n === 0) return { prob: 1, picks: [] }

  const ss = slots.slice(0, n)

  // Build team → bit index
  const allTeamIds: string[] = []
  const seen = new Set<string>()
  for (const s of ss) {
    for (const o of s.options) {
      if (!seen.has(o.teamId)) {
        seen.add(o.teamId)
        allTeamIds.push(o.teamId)
      }
    }
  }

  if (allTeamIds.length > 22) return solveGreedy(slots, horizon)

  const tidToBit: Record<string, number> = {}
  allTeamIds.forEach((tid, i) => (tidToBit[tid] = 1 << i))

  const memo = new Map<
    string,
    { prob: number; picks: (MatchOption | null)[] }
  >()

  function dp(
    gwIdx: number,
    mask: number,
  ): { prob: number; picks: (MatchOption | null)[] } {
    if (gwIdx === n) return { prob: 1, picks: [] }
    const key = `${gwIdx}:${mask}`
    const cached = memo.get(key)
    if (cached) return cached

    let bestProb = 0
    let bestPicks: (MatchOption | null)[] = []

    for (const opt of ss[gwIdx].options) {
      const bit = tidToBit[opt.teamId] ?? 0
      if (mask & bit) continue
      const future = dp(gwIdx + 1, mask | bit)
      const total = opt.winProb * future.prob
      if (total > bestProb) {
        bestProb = total
        bestPicks = [opt, ...future.picks]
      }
    }

    if (bestProb === 0) {
      bestPicks = new Array(n - gwIdx).fill(null)
    }

    const result = { prob: bestProb, picks: bestPicks }
    memo.set(key, result)
    return result
  }

  return dp(0, 0)
}

// ---- Greedy solver (fallback for large team sets) ----

function solveGreedy(
  slots: GWSlot[],
  horizon: number,
): { prob: number; picks: (MatchOption | null)[] } {
  const n = Math.min(horizon, slots.length)
  const used = new Set<string>()
  const picks: (MatchOption | null)[] = []
  let totalProb = 1

  for (let i = 0; i < n; i++) {
    const available = slots[i].options.filter(
      (o) => !used.has(o.teamId),
    )
    if (available.length === 0) {
      picks.push(null)
      totalProb = 0
      continue
    }

    let bestOpt: MatchOption
    if (i + 1 < n) {
      let bestScore = 0
      bestOpt = available[0]
      for (const opt of available) {
        const nextAvail = slots[i + 1].options.filter(
          (o) => !used.has(o.teamId) && o.teamId !== opt.teamId,
        )
        const nextBest = nextAvail.reduce(
          (max, o) => Math.max(max, o.winProb),
          0,
        )
        const score = opt.winProb * nextBest
        if (score > bestScore) {
          bestScore = score
          bestOpt = opt
        }
      }
    } else {
      bestOpt = available.reduce(
        (best, o) => (o.winProb > best.winProb ? o : best),
        available[0],
      )
    }

    picks.push(bestOpt!)
    used.add(bestOpt!.teamId)
    totalProb *= bestOpt!.winProb
  }

  return { prob: totalProb, picks }
}

// ---- Edge Function handler ----

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders })
  }

  try {
    let gameId: string
    try {
      const body = await req.json()
      gameId = body.game_id
    } catch {
      return new Response(
        JSON.stringify({
          error: 'Invalid JSON body — expected { "game_id": "uuid" }',
        }),
        {
          status: 400,
          headers: {
            ...corsHeaders,
            "Content-Type": "application/json",
          },
        },
      )
    }
    if (!gameId) throw new Error("game_id is required")

    const sb = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    )

    // Load model params
    const { data: paramsRaw } = await sb
      .from("model_params")
      .select("key, value")
    const params: Record<string, number> = {}
    for (const p of paramsRaw ?? []) params[p.key] = Number(p.value)
    const hfa = params.hfa
    const drawBoundary = params.draw_boundary
    if (hfa == null || drawBoundary == null) {
      return new Response(
        JSON.stringify({ error: "Model not calibrated" }),
        {
          status: 400,
          headers: {
            ...corsHeaders,
            "Content-Type": "application/json",
          },
        },
      )
    }

    // Load teams
    const { data: teamsRaw } = await sb
      .from("teams")
      .select("id, name, current_elo")
    const teams: Record<string, any> = {}
    for (const t of teamsRaw ?? []) teams[t.id] = t
    const teamsMap: Record<string, string> = {}
    for (const [tid, t] of Object.entries(teams))
      teamsMap[tid] = (t as any).name
    const aliasToId = buildAliasMap(teamsMap)

    // Load picks for this game
    const { data: picksRaw } = await sb
      .from("lms_picks")
      .select("gameweek, team_id, result")
      .eq("game_id", gameId)
      .order("gameweek")
    const usedTeamIds = new Set((picksRaw ?? []).map((p: any) => p.team_id))
    const currentWeekInGame = (picksRaw ?? []).length + 1

    // Load GW config
    const { data: cfgRaw } = await sb
      .from("lms_gameweek_config")
      .select("gameweek, included")
      .eq("game_id", gameId)
    const gwConfig: Record<number, boolean> = {}
    for (const c of cfgRaw ?? []) gwConfig[c.gameweek] = c.included

    // Load future fixtures
    const now = new Date().toISOString()
    const { data: fixtures } = await sb
      .from("fixtures")
      .select("id, home_team_id, away_team_id, kickoff, gameweek")
      .eq("status", "scheduled")
      .gt("kickoff", now)
      .order("kickoff")

    const allFutureGWs = new Set<number>()
    for (const f of fixtures ?? [])
      if (f.gameweek) allFutureGWs.add(f.gameweek)
    const includedGWs = new Set<number>()
    for (const gw of allFutureGWs)
      if (gwConfig[gw] !== false) includedGWs.add(gw)

    // Load market odds (chunked)
    const fixtureIds = (fixtures ?? [])
      .filter((f: any) => f.id)
      .map((f: any) => f.id)
    let oddsRows: any[] = []
    for (let i = 0; i < fixtureIds.length; i += 50) {
      const chunk = fixtureIds.slice(i, i + 50)
      const { data } = await sb
        .from("market_odds")
        .select(
          "fixture_id, bookmaker_key, outcome_name, outcome_price",
        )
        .eq("market_key", "h2h")
        .in("bookmaker_key", BOOKMAKER_PRIORITY)
        .in("fixture_id", chunk)
      oddsRows = oddsRows.concat(data ?? [])
    }

    // Group + pick best bookmaker
    const rawOdds: Record<
      string,
      Record<string, Record<string, number>>
    > = {}
    for (const r of oddsRows) {
      if (!rawOdds[r.fixture_id]) rawOdds[r.fixture_id] = {}
      if (!rawOdds[r.fixture_id][r.bookmaker_key])
        rawOdds[r.fixture_id][r.bookmaker_key] = {}
      rawOdds[r.fixture_id][r.bookmaker_key][r.outcome_name] = Number(
        r.outcome_price,
      )
    }

    const marketWinProbs: Record<
      string,
      { home: number; away: number }
    > = {}
    for (const [fid, bkMap] of Object.entries(rawOdds)) {
      for (const bk of BOOKMAKER_PRIORITY) {
        const outcomes = bkMap[bk]
        if (!outcomes || Object.keys(outcomes).length !== 3) continue
        const fx = (fixtures ?? []).find((f: any) => f.id === fid)
        if (!fx) break
        const oddsH = findOutcomePrice(
          outcomes,
          fx.home_team_id,
          aliasToId,
        )
        const oddsD = outcomes["Draw"]
        const oddsA = findOutcomePrice(
          outcomes,
          fx.away_team_id,
          aliasToId,
        )
        if (oddsH && oddsD && oddsA) {
          const [mH, , mA] = devig(oddsH, oddsD, oddsA)
          marketWinProbs[fid] = { home: mH, away: mA }
        }
        break
      }
    }

    // Run solver
    const horizon = estimateHorizon(
      HISTORICAL_DURATIONS,
      currentWeekInGame,
    )
    const slots = buildGWOptions(
      fixtures ?? [],
      teams,
      hfa,
      drawBoundary,
      usedTeamIds,
      includedGWs,
      marketWinProbs,
    )

    if (slots.length === 0) {
      const meanDur =
        HISTORICAL_DURATIONS.reduce((a, b) => a + b, 0) /
        HISTORICAL_DURATIONS.length
      return new Response(
        JSON.stringify({
          game_id: gameId,
          current_gw: 0,
          horizon,
          expected_duration: meanDur,
          survival_prob: 0,
          picks_plan: [],
          all_options: [],
          used_teams: [],
          included_gws: [...includedGWs].sort((a, b) => a - b),
          excluded_gws: [...allFutureGWs]
            .filter((g) => !includedGWs.has(g))
            .sort((a, b) => a - b),
        }),
        {
          headers: {
            ...corsHeaders,
            "Content-Type": "application/json",
          },
        },
      )
    }

    const currentGW = slots[0].gameweek
    const { prob, picks: pickSeq } = solveDP(slots, horizon)

    const picksPlan = pickSeq.map((pick, i) => {
      const gw = i < slots.length ? slots[i].gameweek : null
      if (!pick)
        return { gameweek: gw, team_name: null, win_prob: 0 }
      return {
        gameweek: gw,
        team_id: pick.teamId,
        team_name: pick.teamName,
        opponent_name: pick.opponentName,
        is_home: pick.isHome,
        win_prob: Math.round(pick.winProb * 1000) / 10,
        team_elo: pick.teamElo,
        opponent_elo: pick.opponentElo,
        source: pick.source,
      }
    })

    const allOptions = slots[0].options
      .sort((a, b) => b.winProb - a.winProb)
      .map((o) => ({
        team_id: o.teamId,
        team_name: o.teamName,
        opponent_name: o.opponentName,
        is_home: o.isHome,
        win_prob: Math.round(o.winProb * 1000) / 10,
        team_elo: o.teamElo,
        opponent_elo: o.opponentElo,
        source: o.source,
      }))

    const usedTeams = (picksRaw ?? []).map((p: any) => ({
      gameweek: p.gameweek,
      team_name: teams[p.team_id]?.name ?? "Unknown",
      team_id: p.team_id,
      result: p.result,
    }))

    const meanDur =
      HISTORICAL_DURATIONS.reduce((a, b) => a + b, 0) /
      HISTORICAL_DURATIONS.length

    return new Response(
      JSON.stringify({
        game_id: gameId,
        current_gw: currentGW,
        horizon,
        expected_duration: Math.round(meanDur * 10) / 10,
        survival_prob: Math.round(prob * 10000) / 100,
        picks_plan: picksPlan,
        all_options: allOptions,
        used_teams: usedTeams,
        included_gws: [...includedGWs].sort((a, b) => a - b),
        excluded_gws: [...allFutureGWs]
          .filter((g) => !includedGWs.has(g))
          .sort((a, b) => a - b),
      }),
      {
        headers: {
          ...corsHeaders,
          "Content-Type": "application/json",
        },
      },
    )
  } catch (err: any) {
    return new Response(
      JSON.stringify({ error: err.message }),
      {
        status: 500,
        headers: {
          ...corsHeaders,
          "Content-Type": "application/json",
        },
      },
    )
  }
})
