import { useQuery } from '@tanstack/react-query'
import { fetchBudgetTimeline, type BudgetSnapshot } from './api'
import { rupees } from './format'

const W = 720
const H = 240
const PAD = { top: 16, right: 16, bottom: 28, left: 64 }

/** The whole Recovery Budget at a snapshot: spent + available + reserved (BudgetLedger.remaining + spent). */
function total(s: BudgetSnapshot): number {
  return s.spent + s.available + s.reserved
}

function linePath(values: number[], yMax: number): string {
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const step = values.length > 1 ? innerW / (values.length - 1) : 0
  return values
    .map((v, i) => {
      const x = PAD.left + i * step
      const y = PAD.top + innerH * (1 - (yMax === 0 ? 0 : v / yMax))
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-faint">{label}</p>
      <p className="mt-0.5 font-mono text-sm text-ink">{value}</p>
    </div>
  )
}

const SERIES = [
  { name: 'reserved', className: 'stroke-kicker', swatch: 'bg-kicker', key: 'reserved' as const },
  { name: 'available', className: 'stroke-brand', swatch: 'bg-brand', key: 'available' as const },
  { name: 'spent', className: 'stroke-bad', swatch: 'bg-bad', key: 'spent' as const },
]

function Chart({ snapshots }: { snapshots: BudgetSnapshot[] }) {
  const yMax = Math.max(...snapshots.map(total), 1)
  const innerH = H - PAD.top - PAD.bottom

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[600px] max-w-[880px]" role="img" aria-label="Reserved budget over the run">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const y = PAD.top + innerH * (1 - t)
          return (
            <g key={t}>
              <line x1={PAD.left} y1={y} x2={W - PAD.right} y2={y} className="stroke-border" />
              <text x={PAD.left - 8} y={y + 3} textAnchor="end" className="fill-faint text-[10px]">
                {rupees(yMax * t)}
              </text>
            </g>
          )
        })}
        {SERIES.map((s) => (
          <path
            key={s.name}
            d={linePath(snapshots.map((snap) => snap[s.key]), yMax)}
            fill="none"
            className={s.className}
            strokeWidth={2}
          />
        ))}
        <text x={PAD.left} y={H - 8} className="fill-faint text-[10px]">
          arrival order → ({snapshots.length} allocation decisions)
        </text>
      </svg>
      <div className="mt-2 flex flex-wrap gap-4 text-xs text-muted">
        {SERIES.map((s) => (
          <span key={s.name} className="flex items-center gap-1.5">
            <span className={`inline-block h-2 w-4 rounded ${s.swatch}`} />
            {s.name}
          </span>
        ))}
      </div>
    </div>
  )
}

export function BudgetTimelineView() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['budget-timeline'],
    queryFn: fetchBudgetTimeline,
    refetchInterval: 3000,
  })

  if (isLoading) return <p className="text-muted">Loading budget timeline…</p>
  if (isError) return <p className="text-bad">{String(error)}</p>
  if (!data || data.length === 0) {
    return (
      <p className="rounded-lg border border-warn/30 bg-warn-wash px-3 py-2.5 text-sm text-warn">
        No allocation decisions yet. Run <span className="codechip">uv run python -m app.demo_seed</span>.
      </p>
    )
  }

  const last = data[data.length - 1]
  const funded = data.filter((s) => s.funded).length

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        The Reserved Budget as a moving quantity — one point per Streaming Allocator decision, in the order cases arrived.
      </p>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="budget" value={rupees(total(last))} />
        <Stat label="reserved" value={rupees(last.reserved)} />
        <Stat label="available" value={rupees(last.available)} />
        <Stat label="spent" value={rupees(last.spent)} />
        <Stat label="decisions" value={String(data.length)} />
        <Stat label="funded" value={`${funded}/${data.length}`} />
      </div>

      <div className="card p-4">
        <Chart snapshots={data} />
      </div>
    </div>
  )
}
