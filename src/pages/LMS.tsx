import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { supabase } from '@/lib/supabase'
import type { Team, LMSGame, SolverResult } from '@/lib/types'
import SolverOutput from '@/components/SolverOutput'

export default function LMS() {
  const [teams, setTeams] = useState<Team[]>([])
  const [games, setGames] = useState<LMSGame[]>([])
  const [currentGameId, setCurrentGameId] = useState<string | null>(null)
  const [solverResult, setSolverResult] = useState<SolverResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [solverLoading, setSolverLoading] = useState(false)
  const [status, setStatus] = useState('')

  // Pick form state
  const [pickGW, setPickGW] = useState('')
  const [pickTeamId, setPickTeamId] = useState('')
  const [pickResult, setPickResult] = useState('')

  const currentGame = games.find((g) => g.id === currentGameId) ?? null

  useEffect(() => {
    loadTeams()
    loadGames()
  }, [])

  async function loadTeams() {
    const { data } = await supabase
      .from('teams')
      .select('id, name, current_elo')
      .order('name')
    setTeams(data ?? [])
  }

  async function loadGames() {
    setLoading(true)
    try {
      const { data: gamesData } = await supabase
        .from('lms_games')
        .select('*')
        .order('created_at', { ascending: false })

      const enriched: LMSGame[] = []
      for (const g of gamesData ?? []) {
        const { data: picks } = await supabase
          .from('lms_picks')
          .select('gameweek, team_id, result')
          .eq('game_id', g.id)
          .order('gameweek')
        const { data: cfg } = await supabase
          .from('lms_gameweek_config')
          .select('gameweek, included')
          .eq('game_id', g.id)

        const gwConfig: Record<number, boolean> = {}
        for (const c of cfg ?? []) gwConfig[c.gameweek] = c.included

        enriched.push({ ...g, picks: picks ?? [], gw_config: gwConfig })
      }

      setGames(enriched)
      if (!currentGameId && enriched.length > 0) {
        setCurrentGameId(enriched[0].id)
      }
    } finally {
      setLoading(false)
    }
  }

  async function createGame() {
    const name = prompt('Game name:')
    if (!name) return
    const { data } = await supabase
      .from('lms_games')
      .insert({ name })
      .select()
      .single()
    if (data) {
      setCurrentGameId(data.id)
      await loadGames()
    }
  }

  async function addPick() {
    if (!currentGameId || !pickGW || !pickTeamId) return
    const payload: any = {
      game_id: currentGameId,
      gameweek: parseInt(pickGW),
      team_id: pickTeamId,
    }
    if (pickResult) payload.result = pickResult
    await supabase
      .from('lms_picks')
      .upsert(payload, { onConflict: 'game_id,gameweek' })
    setPickGW('')
    setPickTeamId('')
    setPickResult('')
    await loadGames()
  }

  async function removePick(gameweek: number) {
    if (!currentGameId) return
    await supabase
      .from('lms_picks')
      .delete()
      .eq('game_id', currentGameId)
      .eq('gameweek', gameweek)
    await loadGames()
  }

  async function runSolver() {
    if (!currentGameId) return
    setSolverLoading(true)
    setStatus('Running solver...')
    try {
      const { data, error } = await supabase.functions.invoke(
        'lms-recommend',
        { body: { game_id: currentGameId } },
      )
      if (error) throw error
      setSolverResult(data)
      setStatus('')
    } catch (err: any) {
      setStatus(`Solver failed: ${err.message}`)
    } finally {
      setSolverLoading(false)
    }
  }

  const handleToggleGW = useCallback(
    async (gw: number, included: boolean) => {
      if (!currentGameId) return
      await supabase.from('lms_gameweek_config').upsert(
        { game_id: currentGameId, gameweek: gw, included },
        { onConflict: 'game_id,gameweek' },
      )
      await loadGames()
      // Re-run solver after toggling
      setSolverLoading(true)
      setStatus('Re-running solver...')
      try {
        const { data, error } = await supabase.functions.invoke(
          'lms-recommend',
          { body: { game_id: currentGameId } },
        )
        if (error) throw error
        setSolverResult(data)
        setStatus('')
      } catch (err: any) {
        setStatus(`Solver failed: ${err.message}`)
      } finally {
        setSolverLoading(false)
      }
    },
    [currentGameId],
  )

  function teamName(teamId: string): string {
    return teams.find((t) => t.id === teamId)?.name ?? 'Unknown'
  }

  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      <div className="max-w-4xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">LMS Advisor</h1>
          <Link
            to="/"
            className="text-accent-blue hover:underline text-sm font-medium"
          >
            ← Elo vs Market
          </Link>
        </div>

        {/* Game selector */}
        <div className="flex flex-wrap gap-3 mb-6">
          <select
            value={currentGameId ?? ''}
            onChange={(e) => {
              setCurrentGameId(e.target.value)
              setSolverResult(null)
            }}
            className="bg-bg-card border border-border-primary rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
          >
            <option value="">Select a game...</option>
            {games.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name} ({g.picks.length} picks) — {g.status}
              </option>
            ))}
          </select>
          <button
            onClick={createGame}
            className="px-4 py-2 bg-bg-card border border-border-primary rounded-lg text-sm font-medium hover:bg-bg-hover transition-colors"
          >
            New Game
          </button>
          <button
            onClick={runSolver}
            disabled={!currentGameId || solverLoading}
            className="px-4 py-2 bg-accent-blue text-white rounded-lg text-sm font-medium hover:bg-blue-600 disabled:opacity-50 transition-colors"
          >
            {solverLoading ? 'Running...' : 'Run Solver'}
          </button>
        </div>

        {/* Status */}
        {status && (
          <div className="text-sm text-text-secondary bg-bg-card border border-border-primary rounded-lg px-4 py-2 mb-4">
            {status}
          </div>
        )}

        {loading ? (
          <div className="text-center text-text-secondary py-12">
            Loading games...
          </div>
        ) : (
          currentGame && (
            <>
              {/* Pick history */}
              <div className="mb-6">
                <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-3">
                  Picks — {currentGame.name}
                </h2>
                {currentGame.picks.length === 0 ? (
                  <p className="text-text-muted text-sm">No picks yet</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {currentGame.picks.map((p) => (
                      <div
                        key={p.gameweek}
                        className="flex items-center gap-1 px-3 py-1.5 bg-bg-card border border-border-primary rounded-full text-sm"
                      >
                        <span className="text-text-secondary">
                          GW{p.gameweek}
                        </span>
                        <span className="font-medium">
                          {teamName(p.team_id)}
                        </span>
                        {p.result && (
                          <span
                            className={`font-bold ${
                              p.result === 'W'
                                ? 'text-accent-green'
                                : p.result === 'L'
                                  ? 'text-accent-red'
                                  : 'text-accent-yellow'
                            }`}
                          >
                            {p.result}
                          </span>
                        )}
                        <button
                          onClick={() => removePick(p.gameweek)}
                          className="ml-1 text-text-muted hover:text-accent-red transition-colors"
                        >
                          ×
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Add pick form */}
              <div className="mb-6 p-4 bg-bg-card border border-border-primary rounded-lg">
                <h3 className="text-sm font-semibold text-text-secondary mb-3">
                  Add a Pick
                </h3>
                <div className="flex flex-wrap gap-3 items-end">
                  <div>
                    <label className="block text-xs text-text-muted mb-1">
                      Gameweek
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={38}
                      value={pickGW}
                      onChange={(e) => setPickGW(e.target.value)}
                      className="bg-bg-primary border border-border-primary rounded-lg px-3 py-2 text-sm w-20 focus:outline-none focus:border-accent-blue"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-text-muted mb-1">
                      Team
                    </label>
                    <select
                      value={pickTeamId}
                      onChange={(e) => setPickTeamId(e.target.value)}
                      className="bg-bg-primary border border-border-primary rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent-blue"
                    >
                      <option value="">Select team...</option>
                      {teams.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name} (ELO {t.current_elo.toFixed(0)})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-text-muted mb-1">
                      Result
                    </label>
                    <select
                      value={pickResult}
                      onChange={(e) => setPickResult(e.target.value)}
                      className="bg-bg-primary border border-border-primary rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent-blue"
                    >
                      <option value="">Pending</option>
                      <option value="W">Won</option>
                      <option value="D">Draw</option>
                      <option value="L">Lost</option>
                    </select>
                  </div>
                  <button
                    onClick={addPick}
                    disabled={!pickGW || !pickTeamId}
                    className="px-4 py-2 bg-accent-blue text-white rounded-lg text-sm font-medium hover:bg-blue-600 disabled:opacity-50 transition-colors"
                  >
                    Add Pick
                  </button>
                </div>
              </div>
            </>
          )
        )}

        {/* Solver output */}
        {solverResult && (
          <SolverOutput result={solverResult} onToggleGW={handleToggleGW} />
        )}
      </div>
    </div>
  )
}
