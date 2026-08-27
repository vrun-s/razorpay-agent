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
            <span className={`w-32 shrink-0 ${isAI ? 'font-semibold text-gray-900' : 'text-gray-600'}`}>
              {ARM_LABELS[name]}
            </span>
            <div className="h-5 flex-1 rounded bg-gray-100">
              <div
                className={`h-5 rounded ${isAI ? 'bg-blue-600' : 'bg-gray-400'}`}
                style={{ width: `${(arm.total_nrr / max) * 100}%` }}
              />
            </div>
            <span className="w-28 shrink-0 text-right font-mono text-xs text-gray-700">{rupees(arm.total_nrr)}</span>
            <span className="w-24 shrink-0 text-right text-xs text-gray-400">
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
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-gray-400">Incremental NRR vs {ARM_LABELS[name] ?? name}</p>
      <p className="mt-0.5 font-mono text-sm text-gray-900">
        {rupees(meanGap)} <span className="text-gray-400">per case</span>
      </p>
      <p className="text-xs text-gray-500">
        95% bootstrap CI [{rupees(lo)}, {rupees(hi)}] on the per-case paired gap (ADR-0013)
      </p>
      <p className="text-[11px] text-gray-400">≈ {rupees(meanGap * caseCount)} over the {caseCount}-case batch</p>
      <p className={`mt-1 text-[11px] font-medium ${clearsZero ? 'text-green-700' : 'text-amber-700'}`}>
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
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${S} ${S}`} className="min-w-[240px]" role="img" aria-label="Calibration curve">
        <rect x={pad} y={pad} width={inner} height={inner} fill="none" stroke="#e2e8f0" />
        <line x1={pad} y1={y(0)} x2={x(1)} y2={y(1)} stroke="#cbd5e1" strokeDasharray="4 3" />
        {[0, 0.5, 1].map((t) => (
          <g key={t}>
            <text x={x(t)} y={S - 8} textAnchor="middle" className="fill-gray-400 text-[9px]">
              {t}
            </text>
            <text x={10} y={y(t) + 3} className="fill-gray-400 text-[9px]">
              {t}
            </text>
          </g>
        ))}
        <text x={x(0.5)} y={S - 20} textAnchor="middle" className="fill-gray-500 text-[10px]">
          predicted
        </text>
        <text x={14} y={y(0.5)} textAnchor="middle" transform={`rotate(-90 14 ${y(0.5)})`} className="fill-gray-500 text-[10px]">
          observed
        </text>
        <polyline
          points={buckets.map((b) => `${x(b.mean_predicted)},${y(b.observed_rate)}`).join(' ')}
          fill="none"
          stroke="#2563eb"
          strokeWidth={1.5}
        />
        {buckets.map((b, i) => (
          <circle
            key={i}
            cx={x(b.mean_predicted)}
            cy={y(b.observed_rate)}
            r={3 + 5 * Math.sqrt(b.count / maxCount)}
            fill="#2563eb"
            fillOpacity={0.5}
            stroke="#2563eb"
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

  if (isLoading) return <p className="text-gray-500">Loading evaluation report…</p>
  if (isError) return <p className="text-red-600">{String(error)}</p>
  if (!data) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-5 text-sm text-gray-600 shadow-sm">
        <p>No evaluation report generated yet.</p>
        <p className="mt-2">
          Run <code className="rounded bg-gray-100 px-1.5 py-0.5">uv run python -m app.evaluation</code> from{' '}
          <code>backend/</code> to produce it (ticket 15's harness, ADR-0013).
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-gray-500">
        Sourced from ticket 15's evaluation harness{data.split ? ` — ${data.split} split` : ''}, run seed{' '}
        <span className="font-mono">{data.run_seed}</span>. Paired counterfactual replay across all four arms (ADR-0013).
      </p>

      <section className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-900">Total Net Recovered Revenue by arm</h3>
        <p className="mt-0.5 text-xs text-gray-500">Sum of per-case NRR over the whole batch (ADR-0013).</p>
        <div className="mt-3">
          <NrrBars report={data} />
        </div>
      </section>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
          <p className="text-[11px] uppercase tracking-wide text-blue-700">% of offline-optimal captured</p>
          <p className="mt-1 font-mono text-2xl text-blue-900">{pct(data.pct_of_offline_optimal)}</p>
          <p className="mt-1 text-[11px] text-blue-700/80">AI total NRR ÷ offline-optimal total NRR</p>
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

      <section className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-900">Estimator calibration</h3>
        <p className="mt-1 text-xs text-gray-500">
          Predicted vs. observed recovery probability, fixed-width bins; dot size ∝ √count. On the dashed diagonal = perfectly
          calibrated.
        </p>
        <div className="mt-2">
          {data.calibration.length === 0 ? (
            <p className="text-sm text-gray-500">No resolved decisions in this run.</p>
          ) : (
            <CalibrationCurve buckets={data.calibration} />
          )}
        </div>
      </section>
    </div>
  )
}
