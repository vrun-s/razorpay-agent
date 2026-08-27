import { useQuery } from '@tanstack/react-query'
import { fetchEvaluationReport, type CalibrationBucket, type EvaluationReport } from './api'
import { pct, rupees } from './format'

const ARM_ORDER = ['no_intervention', 'fixed_rule', 'ai_treatment', 'offline_optimal'] as const
const ARM_LABELS: Record<string, string> = {
  no_intervention: 'No intervention',
  fixed_rule: 'Fixed rule (5%)',
  ai_treatment: 'AI treatment',
  offline_optimal: 'Offline-optimal',
}

function NrrBars({ report }: { report: EvaluationReport }) {
  const max = Math.max(...Object.values(report.arms).map((a) => a.total_nrr), 1)
  return (
    <div className="space-y-2">
      {ARM_ORDER.filter((name) => report.arms[name]).map((name) => {
        const arm = report.arms[name]
        const isAI = name === 'ai_treatment'
        return (
          <div key={name} className="flex items-center gap-3 text-sm">
            <span className={`w-32 shrink-0 ${isAI ? 'font-semibold text-ink' : 'text-muted'}`}>{ARM_LABELS[name]}</span>
            <div className="h-5 flex-1 rounded bg-surface-2">
              <div
                className={`h-5 rounded ${isAI ? 'bg-brand' : 'bg-faint'}`}
                style={{ width: `${(arm.total_nrr / max) * 100}%` }}
              />
            </div>
            <span className="w-28 shrink-0 text-right font-mono text-xs text-ink">{rupees(arm.total_nrr)}</span>
            <span className="w-24 shrink-0 text-right text-xs text-faint">
              {arm.recovered_count}/{arm.case_count} rec.
            </span>
          </div>
        )
      })}
    </div>
  )
}

function IncrementalRow({
  name,
  meanGap,
  lo,
  hi,
  caseCount,
}: {
  name: string
  meanGap: number
  lo: number
  hi: number
  caseCount: number
}) {
  const clearsZero = lo > 0
  return (
    <div className="card px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-faint">Incremental NRR vs {ARM_LABELS[name] ?? name}</p>
      <p className="mt-0.5 font-mono text-sm text-ink">
        {rupees(meanGap)} <span className="text-faint">per case</span>
      </p>
      <p className="text-xs text-muted">
        95% bootstrap CI [{rupees(lo)}, {rupees(hi)}] on the per-case paired gap (ADR-0013)
      </p>
      <p className="text-[11px] text-faint">≈ {rupees(meanGap * caseCount)} over the {caseCount}-case batch</p>
      <p className={`mt-1 text-[11px] font-semibold ${clearsZero ? 'text-ok' : 'text-warn'}`}>
        {clearsZero ? 'interval clears zero' : 'interval includes zero'}
      </p>
    </div>
  )
}

function CalibrationCurve({ buckets }: { buckets: CalibrationBucket[] }) {
  const S = 260
  const pad = 34
  const inner = S - pad * 2
  const x = (v: number) => pad + v * inner
  const y = (v: number) => pad + (1 - v) * inner
  const maxCount = Math.max(...buckets.map((b) => b.count), 1)

  return (
    <div className="max-w-[320px]">
      <svg viewBox={`0 0 ${S} ${S}`} className="w-full" role="img" aria-label="Calibration curve">
        <rect x={pad} y={pad} width={inner} height={inner} fill="none" className="stroke-border" />
        <line x1={pad} y1={y(0)} x2={x(1)} y2={y(1)} className="stroke-faint" strokeDasharray="4 3" />
        {[0, 0.5, 1].map((t) => (
          <g key={t}>
            <text x={x(t)} y={S - 8} textAnchor="middle" className="fill-faint text-[9px]">
              {t}
            </text>
            <text x={10} y={y(t) + 3} className="fill-faint text-[9px]">
              {t}
            </text>
          </g>
        ))}
        <text x={x(0.5)} y={S - 20} textAnchor="middle" className="fill-muted text-[10px]">
          predicted
        </text>
        <text
          x={14}
          y={y(0.5)}
          textAnchor="middle"
          transform={`rotate(-90 14 ${y(0.5)})`}
          className="fill-muted text-[10px]"
        >
          observed
        </text>
        <polyline
          points={buckets.map((b) => `${x(b.mean_predicted)},${y(b.observed_rate)}`).join(' ')}
          fill="none"
          className="stroke-brand"
          strokeWidth={1.5}
        />
        {buckets.map((b, i) => (
          <circle
            key={i}
            cx={x(b.mean_predicted)}
            cy={y(b.observed_rate)}
            r={3 + 5 * Math.sqrt(b.count / maxCount)}
            className="fill-brand/50 stroke-brand"
          />
        ))}
      </svg>
    </div>
  )
}

export function EvaluationView() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['evaluation-report'],
    queryFn: fetchEvaluationReport,
    refetchInterval: 10000,
  })

  if (isLoading) return <p className="text-muted">Loading evaluation report…</p>
  if (isError) return <p className="text-bad">{String(error)}</p>
  if (!data) {
    return (
      <div className="card p-5 text-sm text-muted">
        <p className="text-ink">No evaluation report generated yet.</p>
        <p className="mt-2">
          Run <span className="codechip">uv run python -m app.evaluation</span> from <span className="codechip">backend/</span>{' '}
          to produce it (ticket 15's harness, ADR-0013).
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted">
        Sourced from ticket 15's evaluation harness{data.split ? ` — ${data.split} split` : ''}, run seed{' '}
        <span className="font-mono text-ink">{data.run_seed}</span>. Paired counterfactual replay across all four arms
        (ADR-0013).
      </p>

      <section className="card p-5">
        <p className="kicker">Net Recovered Revenue</p>
        <h3 className="mt-1 text-sm font-semibold text-ink">Total NRR by arm</h3>
        <p className="mt-0.5 text-xs text-muted">Sum of per-case NRR over the whole batch (ADR-0013).</p>
        <div className="mt-3">
          <NrrBars report={data} />
        </div>
      </section>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-brand/30 bg-brand-wash px-4 py-3">
          <p className="text-[11px] uppercase tracking-wide text-brand">% of offline-optimal captured</p>
          <p className="mt-1 font-mono text-2xl text-brand-strong">{pct(data.pct_of_offline_optimal)}</p>
          <p className="mt-1 text-[11px] text-brand/80">AI total NRR ÷ offline-optimal total NRR</p>
        </div>
        {data.baselines.map((b) => (
          <IncrementalRow
            key={b.baseline_name}
            name={b.baseline_name}
            meanGap={b.incremental_nrr}
            lo={b.ci_lower}
            hi={b.ci_upper}
            caseCount={data.arms.ai_treatment?.case_count ?? 0}
          />
        ))}
      </div>

      <section className="card p-5">
        <p className="kicker">Calibration</p>
        <h3 className="mt-1 text-sm font-semibold text-ink">Predicted vs. observed recovery probability</h3>
        <p className="mt-1 text-xs text-muted">
          Fixed-width bins; dot size ∝ √count. On the dashed diagonal = perfectly calibrated.
        </p>
        <div className="mt-2">
          {data.calibration.length === 0 ? (
            <p className="text-sm text-muted">No resolved decisions in this run.</p>
          ) : (
            <CalibrationCurve buckets={data.calibration} />
          )}
        </div>
      </section>
    </div>
  )
}
