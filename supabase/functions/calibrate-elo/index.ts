import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
}

const ELO_SCALE = 400
const BOOKMAKER_PRIORITY = ["pinnacle_closing", "bet365_closing", "market_avg"]

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

// ---- ELO model ----

function elo1x2(
  rHome: number,
  rAway: number,
  hfa: number,
  db: number,
): [number, number, number] {
  const dr = rHome + hfa - rAway
  const pH = 1 / (1 + Math.pow(10, -(dr - db) / ELO_SCALE))
  const pA = 1 / (1 + Math.pow(10, (dr + db) / ELO_SCALE))
  return [pH, 1 - pH - pA, pA]
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

// ---- Optimisation (Adam + projected gradient descent) ----

interface Datum {
  homeIdx: number
  awayIdx: number
  pH: number
  pD: number
  pA: number
}

function objective(x: Float64Array, data: Datum[]): number {
  const eps = 1e-9
  const n = x.length
  const hfa = x[n - 2],
    db = x[n - 1]
  let loss = 0
  for (const d of data) {
    let [eH, eD, eA] = elo1x2(x[d.homeIdx], x[d.awayIdx], hfa, db)
    eH = Math.max(eps, Math.min(1 - eps, eH))
    eD = Math.max(eps, Math.min(1 - eps, eD))
    eA = Math.max(eps, Math.min(1 - eps, eA))
    loss -= d.pH * Math.log(eH) + d.pD * Math.log(eD) + d.pA * Math.log(eA)
  }
  return loss
}

function optimize(
  x: Float64Array,
  data: Datum[],
  nTeams: number,
  maxIter = 1000,
): Float64Array {
  const n = x.length
  const h = 1.0 // finite-diff step
  const lr = 5.0
  const beta1 = 0.9,
    beta2 = 0.999,
    epsAd = 1e-8
  const m = new Float64Array(n)
  const v = new Float64Array(n)

  let prevLoss = objective(x, data)

  for (let t = 1; t <= maxIter; t++) {
    // Numerical gradient (central differences)
    const grad = new Float64Array(n)
    for (let i = 0; i < n; i++) {
      x[i] += h
      const fp = objective(x, data)
      x[i] -= 2 * h
      const fm = objective(x, data)
      x[i] += h // restore
      grad[i] = (fp - fm) / (2 * h)
    }

    // Adam update
    for (let i = 0; i < n; i++) {
      m[i] = beta1 * m[i] + (1 - beta1) * grad[i]
      v[i] = beta2 * v[i] + (1 - beta2) * grad[i] * grad[i]
      const mHat = m[i] / (1 - Math.pow(beta1, t))
      const vHat = v[i] / (1 - Math.pow(beta2, t))
      x[i] -= lr * mHat / (Math.sqrt(vHat) + epsAd)
    }

    // Project: mean rating = 1500
    let sum = 0
    for (let i = 0; i < nTeams; i++) sum += x[i]
    const shift = 1500 - sum / nTeams
    for (let i = 0; i < nTeams; i++) x[i] += shift

    // Bounds
    if (x[n - 2] < 0) x[n - 2] = 0 // HFA >= 0
    if (x[n - 1] < 1) x[n - 1] = 1 // draw_boundary >= 1

    // Early stopping
    const loss = objective(x, data)
    if (Math.abs(loss - prevLoss) < 1e-10) break
    prevLoss = loss
  }

  return x
}

// ---- Edge Function handler ----

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders })
  }

  try {
    const sb = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    )

    // Load completed fixtures
    const { data: fixtures } = await sb
      .from("fixtures")
      .select("id, home_team_id, away_team_id")
      .eq("status", "completed")

    // Load teams
    const { data: teamsRaw } = await sb.from("teams").select("id, name")
    const teamsMap: Record<string, string> = {}
    for (const t of teamsRaw ?? []) teamsMap[t.id] = t.name
    const aliasToId = buildAliasMap(teamsMap)

    const teamIds = Object.keys(teamsMap).sort()
    const teamIndex: Record<string, number> = {}
    teamIds.forEach((tid, i) => (teamIndex[tid] = i))
    const nTeams = teamIds.length

    // Load h2h odds (chunked)
    const fixtureIds = (fixtures ?? []).map((f: any) => f.id)
    const CHUNK = 50
    let allOddsRows: any[] = []
    for (let i = 0; i < fixtureIds.length; i += CHUNK) {
      const chunk = fixtureIds.slice(i, i + CHUNK)
      const { data } = await sb
        .from("market_odds")
        .select("fixture_id, bookmaker_key, outcome_name, outcome_price")
        .eq("market_key", "h2h")
        .in("bookmaker_key", BOOKMAKER_PRIORITY)
        .in("fixture_id", chunk)
      allOddsRows = allOddsRows.concat(data ?? [])
    }

    // Group: fixture_id → bookmaker → outcomes
    const raw: Record<string, Record<string, Record<string, number>>> = {}
    for (const r of allOddsRows) {
      if (!raw[r.fixture_id]) raw[r.fixture_id] = {}
      if (!raw[r.fixture_id][r.bookmaker_key])
        raw[r.fixture_id][r.bookmaker_key] = {}
      raw[r.fixture_id][r.bookmaker_key][r.outcome_name] = Number(
        r.outcome_price,
      )
    }

    // Pick best bookmaker per fixture
    const best: Record<
      string,
      { outcomes: Record<string, number>; source: string }
    > = {}
    for (const [fid, bkMap] of Object.entries(raw)) {
      for (const bk of BOOKMAKER_PRIORITY) {
        const outcomes = bkMap[bk]
        if (outcomes && Object.keys(outcomes).length === 3) {
          best[fid] = { outcomes, source: bk }
          break
        }
      }
    }

    // Build training data
    const training: Datum[] = []
    for (const fx of fixtures ?? []) {
      const entry = best[fx.id]
      if (!entry) continue
      if (
        !(fx.home_team_id in teamIndex) ||
        !(fx.away_team_id in teamIndex)
      )
        continue

      const oddsH = findOutcomePrice(
        entry.outcomes,
        fx.home_team_id,
        aliasToId,
      )
      const oddsD = entry.outcomes["Draw"]
      const oddsA = findOutcomePrice(
        entry.outcomes,
        fx.away_team_id,
        aliasToId,
      )
      if (!oddsH || !oddsD || !oddsA) continue

      const [pH, pD, pA] = devig(oddsH, oddsD, oddsA)
      training.push({
        homeIdx: teamIndex[fx.home_team_id],
        awayIdx: teamIndex[fx.away_team_id],
        pH,
        pD,
        pA,
      })
    }

    if (training.length === 0) {
      return new Response(
        JSON.stringify({
          ok: false,
          error:
            "No training data — run fetch_odds and fetch_historic_odds first",
        }),
        {
          status: 400,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        },
      )
    }

    // Initialise and optimise
    const x = new Float64Array(nTeams + 2)
    for (let i = 0; i < nTeams; i++) x[i] = 1500
    x[nTeams] = 65 // HFA
    x[nTeams + 1] = 85 // draw boundary

    optimize(x, training, nTeams)

    const hfa = x[nTeams]
    const drawBoundary = x[nTeams + 1]
    const finalLoss = objective(x, training)

    // Write calibrated ratings
    for (let i = 0; i < nTeams; i++) {
      await sb
        .from("teams")
        .update({ current_elo: Math.round(x[i] * 100) / 100 })
        .eq("id", teamIds[i])
    }

    // Write model params
    const now = new Date().toISOString()
    await sb.from("model_params").upsert(
      {
        key: "hfa",
        value: Math.round(hfa * 10000) / 10000,
        updated_at: now,
      },
      { onConflict: "key" },
    )
    await sb.from("model_params").upsert(
      {
        key: "draw_boundary",
        value: Math.round(drawBoundary * 10000) / 10000,
        updated_at: now,
      },
      { onConflict: "key" },
    )

    // Build results summary
    const ratings = teamIds
      .map((tid, i) => ({
        name: teamsMap[tid],
        elo: Math.round(x[i] * 10) / 10,
      }))
      .sort((a, b) => b.elo - a.elo)

    return new Response(
      JSON.stringify({
        ok: true,
        message: `Calibrated ${nTeams} teams from ${training.length} fixtures. Loss: ${finalLoss.toFixed(4)}`,
        hfa: Math.round(hfa * 10) / 10,
        draw_boundary: Math.round(drawBoundary * 10) / 10,
        ratings,
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    )
  } catch (err: any) {
    return new Response(
      JSON.stringify({ ok: false, error: err.message }),
      {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      },
    )
  }
})
