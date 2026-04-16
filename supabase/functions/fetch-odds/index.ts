import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders })
  }

  try {
    const oddsApiKey = Deno.env.get("Odds_Api_Key")
    if (!oddsApiKey) throw new Error("Odds_Api_Key secret not set")

    const sb = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    )

    // ---- Fetch EPL events from The Odds API ----
    const url = new URL(
      "https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
    )
    url.searchParams.set("apiKey", oddsApiKey)
    url.searchParams.set("regions", "eu")
    url.searchParams.set("markets", "h2h,spreads,totals")
    url.searchParams.set("oddsFormat", "decimal")
    url.searchParams.set("dateFormat", "iso")

    const resp = await fetch(url.toString())
    if (!resp.ok)
      throw new Error(`Odds API returned ${resp.status}: ${await resp.text()}`)

    const events: any[] = await resp.json()
    const remaining = resp.headers.get("x-requests-remaining") ?? "?"

    let totalOddsRows = 0

    for (const event of events) {
      // Upsert teams
      const { data: homeData } = await sb
        .from("teams")
        .upsert({ name: event.home_team }, { onConflict: "name" })
        .select("id")
        .single()
      const { data: awayData } = await sb
        .from("teams")
        .upsert({ name: event.away_team }, { onConflict: "name" })
        .select("id")
        .single()

      if (!homeData || !awayData) continue

      // Upsert fixture
      const { data: fxData } = await sb
        .from("fixtures")
        .upsert(
          {
            odds_api_event_id: event.id,
            home_team_id: homeData.id,
            away_team_id: awayData.id,
            home_team_name: event.home_team,
            away_team_name: event.away_team,
            kickoff: event.commence_time,
            status: "scheduled",
            has_odds: true,
          },
          { onConflict: "home_team_id,away_team_id" },
        )
        .select("id")
        .single()

      if (!fxData) continue

      // Build odds rows
      const rows: any[] = []
      const capturedAt = new Date().toISOString()
      for (const bk of event.bookmakers ?? []) {
        for (const mkt of bk.markets ?? []) {
          for (const outcome of mkt.outcomes ?? []) {
            rows.push({
              fixture_id: fxData.id,
              bookmaker_key: bk.key,
              bookmaker_title: bk.title,
              market_key: mkt.key,
              outcome_name: outcome.name,
              outcome_price: outcome.price,
              outcome_point: outcome.point ?? null,
              last_update: mkt.last_update,
              captured_at: capturedAt,
            })
          }
        }
      }

      // Upsert in chunks
      for (let i = 0; i < rows.length; i += 500) {
        await sb
          .from("market_odds")
          .upsert(rows.slice(i, i + 500), {
            onConflict:
              "fixture_id,bookmaker_key,market_key,outcome_name",
          })
      }
      totalOddsRows += rows.length
    }

    return new Response(
      JSON.stringify({
        ok: true,
        message: `Fetched ${events.length} events, ${totalOddsRows} odds rows upserted`,
        events_count: events.length,
        odds_rows: totalOddsRows,
        api_requests_remaining: remaining,
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
