import type { SolverResult } from '@/lib/types'

interface Props {
  result: SolverResult
  onToggleGW: (gw: number, included: boolean) => void
}

function sourceBadge(source?: string) {
  if (!source) return null
  const color =
    source === 'market'
      ? 'bg-accent-green'
      : 'bg-accent-yellow text-black'
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${color}`}>
      {source}
    </span>
  )
}

export default function SolverOutput({ result: r, onToggleGW }: Props) {
  const topPick = r.picks_plan[0]

  return (
    <div className="space-y-6">
      {/* Hero recommendation */}
      {topPick && topPick.team_name && (
        <div className="bg-bg-card border-2 border-accent-blue rounded-lg p-6">
          <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">
            Recommended Pick — GW{topPick.gameweek}
          </div>
          <div className="text-2xl font-bold mb-1">
            {topPick.team_name}
            <span className="text-text-secondary text-base ml-2">
              ({topPick.is_home ? 'H' : 'A'}) vs {topPick.opponent_name}
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-4 text-center">
            <div>
              <div className="text-2xl font-bold text-accent-blue">
                {topPick.win_prob}%
              </div>
              <div className="text-xs text-text-secondary">
                Win Prob {sourceBadge(topPick.source)}
              </div>
            </div>
            <div>
              <div className="text-2xl font-bold">{r.survival_prob}%</div>
              <div className="text-xs text-text-secondary">Survival</div>
            </div>
            <div>
              <div className="text-2xl font-bold">{r.horizon}</div>
              <div className="text-xs text-text-secondary">
                Horizon (GWs)
              </div>
            </div>
            <div>
              <div className="text-2xl font-bold">{r.expected_duration}</div>
              <div className="text-xs text-text-secondary">Avg Duration</div>
            </div>
          </div>
        </div>
      )}

      {/* Used teams */}
      {r.used_teams.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-text-secondary mb-2">
            Previous Picks
          </h3>
          <div className="flex flex-wrap gap-2">
            {r.used_teams.map((t) => (
              <span
                key={t.gameweek}
                className="px-3 py-1 bg-bg-card border border-border-primary rounded-full text-sm"
              >
                GW{t.gameweek}{' '}
                <span className="font-medium">{t.team_name}</span>
                {t.result && (
                  <span
                    className={`ml-1 font-bold ${
                      t.result === 'W'
                        ? 'text-accent-green'
                        : t.result === 'L'
                          ? 'text-accent-red'
                          : 'text-accent-yellow'
                    }`}
                  >
                    {t.result}
                  </span>
                )}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Picks plan table */}
      {r.picks_plan.length > 1 && (
        <div>
          <h3 className="text-sm font-semibold text-text-secondary mb-2">
            Optimal Pick Sequence
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-primary text-text-secondary">
                  <th className="text-left py-2 px-3">GW</th>
                  <th className="text-left py-2 px-3">Team</th>
                  <th className="text-left py-2 px-3">Opponent</th>
                  <th className="text-right py-2 px-3">Win %</th>
                  <th className="text-right py-2 px-3">Source</th>
                </tr>
              </thead>
              <tbody>
                {r.picks_plan.map((p, i) => (
                  <tr
                    key={p.gameweek}
                    className={`border-b border-border-primary ${i === 0 ? 'bg-accent-blue/10' : ''}`}
                  >
                    <td className="py-2 px-3">{p.gameweek}</td>
                    <td className="py-2 px-3 font-medium">
                      {p.team_name ?? '—'}
                      {p.is_home !== undefined && (
                        <span className="text-text-muted ml-1">
                          ({p.is_home ? 'H' : 'A'})
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-3 text-text-secondary">
                      {p.opponent_name ?? '—'}
                    </td>
                    <td className="py-2 px-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 bg-bg-primary rounded-full h-2">
                          <div
                            className="bg-accent-blue h-2 rounded-full"
                            style={{ width: `${p.win_prob}%` }}
                          />
                        </div>
                        <span className="font-medium w-12 text-right">
                          {p.win_prob}%
                        </span>
                      </div>
                    </td>
                    <td className="py-2 px-3 text-right">
                      {sourceBadge(p.source)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* All options for current GW */}
      {r.all_options.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-text-secondary mb-2">
            All Options — GW{r.current_gw}
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-primary text-text-secondary">
                  <th className="text-left py-2 px-3">#</th>
                  <th className="text-left py-2 px-3">Team</th>
                  <th className="text-left py-2 px-3">Opponent</th>
                  <th className="text-right py-2 px-3">Win %</th>
                  <th className="text-right py-2 px-3">Source</th>
                </tr>
              </thead>
              <tbody>
                {r.all_options.map((o, i) => (
                  <tr
                    key={o.team_id}
                    className="border-b border-border-primary"
                  >
                    <td className="py-2 px-3 text-text-muted">{i + 1}</td>
                    <td className="py-2 px-3 font-medium">
                      {o.team_name}
                      <span className="text-text-muted ml-1">
                        ({o.is_home ? 'H' : 'A'})
                      </span>
                    </td>
                    <td className="py-2 px-3 text-text-secondary">
                      {o.opponent_name}
                    </td>
                    <td className="py-2 px-3 text-right font-medium">
                      {o.win_prob}%
                    </td>
                    <td className="py-2 px-3 text-right">
                      {sourceBadge(o.source)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* GW config toggles */}
      <div>
        <h3 className="text-sm font-semibold text-text-secondary mb-2">
          Gameweek Config
        </h3>
        <div className="flex flex-wrap gap-2">
          {[...r.included_gws, ...r.excluded_gws]
            .sort((a, b) => a - b)
            .map((gw) => {
              const included = r.included_gws.includes(gw)
              return (
                <button
                  key={gw}
                  onClick={() => onToggleGW(gw, !included)}
                  className={`px-3 py-1 rounded text-sm border transition-colors ${
                    included
                      ? 'bg-accent-blue/20 border-accent-blue text-text-primary'
                      : 'bg-bg-primary border-border-primary text-text-muted line-through opacity-50'
                  }`}
                >
                  GW{gw}
                </button>
              )
            })}
        </div>
      </div>
    </div>
  )
}
