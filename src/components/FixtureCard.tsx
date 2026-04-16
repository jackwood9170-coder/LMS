import type { FixtureComparison } from '@/lib/types'

interface Props {
  fixture: FixtureComparison
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function sourceBadgeColor(source: string | null): string {
  if (!source) return 'bg-gray-600'
  if (source.includes('pinnacle')) return 'bg-accent-blue'
  if (source.includes('bet365')) return 'bg-accent-yellow text-black'
  return 'bg-gray-600'
}

function diffColor(val: number): string {
  if (val > 1.5) return 'text-accent-green'
  if (val < -1.5) return 'text-accent-red'
  return 'text-text-secondary'
}

function fmtPct(v: number): string {
  return v.toFixed(1) + '%'
}

function fmtDiff(v: number): string {
  return (v > 0 ? '+' : '') + v.toFixed(1) + '%'
}

export default function FixtureCard({ fixture: f }: Props) {
  return (
    <div className="bg-bg-card border border-border-primary rounded-lg p-4 mb-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold">{f.homeTeam}</span>
          <span className="text-text-muted">vs</span>
          <span className="font-semibold">{f.awayTeam}</span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          {f.gameweek && (
            <span className="text-text-secondary">GW{f.gameweek}</span>
          )}
          {f.source && (
            <span
              className={`px-2 py-0.5 rounded text-xs font-medium ${sourceBadgeColor(f.source)}`}
            >
              {f.source}
            </span>
          )}
          <span className="text-text-muted">{formatTime(f.kickoff)}</span>
        </div>
      </div>

      {/* Odds grid */}
      <div className="grid grid-cols-4 gap-2 text-sm text-center">
        {/* Column headers */}
        <div className="text-left text-text-secondary" />
        <div className="text-text-secondary font-medium">Home</div>
        <div className="text-text-secondary font-medium">Draw</div>
        <div className="text-text-secondary font-medium">Away</div>

        {/* Market odds row */}
        <div className="text-left text-text-secondary">Market</div>
        {f.market ? (
          <>
            <div>{fmtPct(f.market.home)}</div>
            <div>{fmtPct(f.market.draw)}</div>
            <div>{fmtPct(f.market.away)}</div>
          </>
        ) : (
          <>
            <div className="text-text-muted">—</div>
            <div className="text-text-muted">—</div>
            <div className="text-text-muted">—</div>
          </>
        )}

        {/* ELO model row */}
        <div className="text-left text-accent-blue font-medium">Model</div>
        <div className="text-accent-blue font-bold">
          {fmtPct(f.model.home)}
        </div>
        <div className="text-accent-blue font-bold">
          {fmtPct(f.model.draw)}
        </div>
        <div className="text-accent-blue font-bold">
          {fmtPct(f.model.away)}
        </div>

        {/* Edge/diff row */}
        {f.diff && (
          <>
            <div className="text-left text-text-secondary">Edge</div>
            <div className={diffColor(f.diff.home)}>
              {fmtDiff(f.diff.home)}
            </div>
            <div className={diffColor(f.diff.draw)}>
              {fmtDiff(f.diff.draw)}
            </div>
            <div className={diffColor(f.diff.away)}>
              {fmtDiff(f.diff.away)}
            </div>
          </>
        )}
      </div>

      {/* ELO footer */}
      <div className="flex justify-between mt-3 text-xs text-text-muted">
        <span>ELO {f.homeElo.toFixed(0)}</span>
        <span>ELO {f.awayElo.toFixed(0)}</span>
      </div>
    </div>
  )
}
