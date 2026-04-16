import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { supabase } from '@/lib/supabase'
import { elo1x2, devig } from '@/lib/elo'
import { buildAliasMap, findOutcomePrice } from '@/lib/aliases'
import type { Team, FixtureComparison } from '@/lib/types'
import FixtureCard from '@/components/FixtureCard'

const BOOKMAKER_PRIORITY = [
  'pinnacle',
  'pinnacle_closing',
  'bet365',
  'bet365_closing',
]

export default function Index() {
  const [fixtures, setFixtures] = useState<FixtureComparison[]>([])
  const [modelParams, setModelParams] = useState<{
    hfa: number
    drawBoundary: number
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionStatus, setActionStatus] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [generatedAt, setGeneratedAt] = useState('')

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    setLoading(true)
    try {
      // Parallel queries
      const [teamsRes, paramsRes, fixturesRes] = await Promise.all([
        supabase.from('teams').select('id, name, current_elo'),
        supabase.from('model_params').select('key, value'),
        supabase
          .from('fixtures')
          .select('id, home_team_id, away_team_id, kickoff, gameweek, has_odds')
          .eq('status', 'scheduled')
          .gt('kickoff', new Date().toISOString())
          .order('kickoff'),
      ])

      const teams: Record<string, Team> = {}
      for (const t of teamsRes.data ?? []) teams[t.id] = t

      const params: Record<string, number> = {}
      for (const p of paramsRes.data ?? []) params[p.key] = Number(p.value)

      const hfa = params.hfa
      const drawBoundary = params.draw_boundary
      if (hfa == null || drawBoundary == null) {
        setModelParams(null)
        setFixtures([])
        setLoading(false)
        return
      }
      setModelParams({ hfa, drawBoundary })

      const rawFixtures = fixturesRes.data ?? []
      const fixtureIds = rawFixtures.map((f) => f.id)

      // Load market odds for these fixtures
      let oddsRows: any[] = []
      if (fixtureIds.length > 0) {
        const { data } = await supabase
          .from('market_odds')
          .select('fixture_id, bookmaker_key, outcome_name, outcome_price')
          .eq('market_key', 'h2h')
          .in('bookmaker_key', BOOKMAKER_PRIORITY)
          .in('fixture_id', fixtureIds)
        oddsRows = data ?? []
      }

      // Group odds: fixture_id → bookmaker_key → {outcomeName: price}
      const oddsMap: Record<
        string,
        Record<string, Record<string, number>>
      > = {}
      for (const row of oddsRows) {
        if (!oddsMap[row.fixture_id]) oddsMap[row.fixture_id] = {}
        if (!oddsMap[row.fixture_id][row.bookmaker_key])
          oddsMap[row.fixture_id][row.bookmaker_key] = {}
        oddsMap[row.fixture_id][row.bookmaker_key][row.outcome_name] =
          Number(row.outcome_price)
      }

      // Build alias map
      const teamsMap: Record<string, string> = {}
      for (const [tid, t] of Object.entries(teams)) teamsMap[tid] = t.name
      const aliasToId = buildAliasMap(teamsMap)

      // Build comparison data
      const comparisons: FixtureComparison[] = []
      for (const fx of rawFixtures) {
        const home = teams[fx.home_team_id]
        const away = teams[fx.away_team_id]
        if (!home || !away) continue

        const model = elo1x2(
          home.current_elo,
          away.current_elo,
          hfa,
          drawBoundary,
        )

        const comp: FixtureComparison = {
          id: fx.id,
          homeTeam: home.name,
          awayTeam: away.name,
          homeElo: home.current_elo,
          awayElo: away.current_elo,
          kickoff: fx.kickoff,
          gameweek: fx.gameweek,
          hasOdds: fx.has_odds ?? false,
          model: {
            home: model.home * 100,
            draw: model.draw * 100,
            away: model.away * 100,
          },
          market: null,
          diff: null,
          source: null,
        }

        // Find best bookmaker odds for this fixture
        const fxOdds = oddsMap[fx.id]
        if (fxOdds) {
          for (const bk of BOOKMAKER_PRIORITY) {
            const outcomes = fxOdds[bk]
            if (!outcomes || Object.keys(outcomes).length !== 3) continue

            const oddsH = findOutcomePrice(
              outcomes,
              fx.home_team_id,
              aliasToId,
            )
            const oddsD = outcomes['Draw']
            const oddsA = findOutcomePrice(
              outcomes,
              fx.away_team_id,
              aliasToId,
            )

            if (oddsH && oddsD && oddsA) {
              const mkt = devig(oddsH, oddsD, oddsA)
              comp.source = bk
              comp.market = {
                home: mkt.home * 100,
                draw: mkt.draw * 100,
                away: mkt.away * 100,
              }
              comp.diff = {
                home: (model.home - mkt.home) * 100,
                draw: (model.draw - mkt.draw) * 100,
                away: (model.away - mkt.away) * 100,
              }
              break
            }
          }
        }

        comparisons.push(comp)
      }

      setFixtures(comparisons)
      setGeneratedAt(new Date().toISOString())
    } catch (err) {
      console.error('Failed to load data:', err)
      setActionStatus('Failed to load fixture data')
    } finally {
      setLoading(false)
    }
  }

  async function fetchOdds() {
    setActionLoading(true)
    setActionStatus('Fetching upcoming odds...')
    try {
      const { data, error } = await supabase.functions.invoke('fetch-odds')
      if (error) throw error
      setActionStatus(data?.message ?? 'Odds fetched successfully')
      await loadData()
    } catch (err: any) {
      setActionStatus(`Failed: ${err.message}`)
    } finally {
      setActionLoading(false)
    }
  }

  async function calibrateElo() {
    setActionLoading(true)
    setActionStatus('Calibrating ELO model (may take 10-15s)...')
    try {
      const { data, error } =
        await supabase.functions.invoke('calibrate-elo')
      if (error) throw error
      setActionStatus(data?.message ?? 'ELO calibrated successfully')
      await loadData()
    } catch (err: any) {
      setActionStatus(`Failed: ${err.message}`)
    } finally {
      setActionLoading(false)
    }
  }

  // Group fixtures by date
  const grouped: [string, FixtureComparison[]][] = []
  const dateMap = new Map<string, FixtureComparison[]>()
  for (const fx of fixtures) {
    const dateKey = new Date(fx.kickoff).toLocaleDateString('en-GB', {
      weekday: 'long',
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
    if (!dateMap.has(dateKey)) dateMap.set(dateKey, [])
    dateMap.get(dateKey)!.push(fx)
  }
  for (const [date, fxs] of dateMap) grouped.push([date, fxs])

  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      <div className="max-w-4xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold">Elo vs Market</h1>
            {modelParams && (
              <p className="text-sm text-text-secondary mt-1">
                HFA: {modelParams.hfa.toFixed(1)} | Draw boundary:{' '}
                {modelParams.drawBoundary.toFixed(1)}
                {generatedAt &&
                  ` | Updated: ${new Date(generatedAt).toLocaleTimeString('en-GB')}`}
              </p>
            )}
          </div>
          <Link
            to="/lms"
            className="text-accent-blue hover:underline text-sm font-medium"
          >
            LMS Advisor →
          </Link>
        </div>

        {/* Action buttons */}
        <div className="flex flex-wrap gap-3 mb-4">
          <button
            onClick={fetchOdds}
            disabled={actionLoading}
            className="px-4 py-2 bg-accent-blue text-white rounded-lg font-medium text-sm hover:bg-blue-600 disabled:opacity-50 transition-colors"
          >
            {actionLoading ? 'Working...' : 'Fetch Upcoming Odds'}
          </button>
          <button
            onClick={calibrateElo}
            disabled={actionLoading}
            className="px-4 py-2 bg-bg-card border border-border-primary text-text-primary rounded-lg font-medium text-sm hover:bg-bg-hover disabled:opacity-50 transition-colors"
          >
            Calibrate ELO
          </button>
        </div>

        {/* Status message */}
        {actionStatus && (
          <div className="text-sm text-text-secondary bg-bg-card border border-border-primary rounded-lg px-4 py-2 mb-4">
            {actionStatus}
          </div>
        )}

        {/* Content */}
        {loading ? (
          <div className="text-center text-text-secondary py-12">
            Loading fixtures...
          </div>
        ) : !modelParams ? (
          <div className="text-center text-text-secondary py-12">
            Model not calibrated. Click &quot;Calibrate ELO&quot; to get
            started.
          </div>
        ) : fixtures.length === 0 ? (
          <div className="text-center text-text-secondary py-12">
            No upcoming fixtures found.
          </div>
        ) : (
          grouped.map(([date, fxs]) => (
            <div key={date} className="mb-6">
              <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-3 border-b border-border-primary pb-2">
                {date}
              </h2>
              {fxs.map((fx) => (
                <FixtureCard key={fx.id} fixture={fx} />
              ))}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
