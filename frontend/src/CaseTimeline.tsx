import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchCaseSummaries, fetchCaseTimeline, type CaseFlags, type TimelineStage } from './api'
import { STATUS_BADGE, clockTime, pct, shortId } from './format'

const FLAG_LABELS: { key: keyof CaseFlags; label: string; className: string }[] = [
  { key: 'no_action_recovered', label: 'NO_ACTION recovered', className: 'bg-green-50 text-green-700 ring-green-600/20' },
  { key: 'policy_rejected', label: 'policy rejection', className: 'bg-red-50 text-red-700 ring-red-600/20' },
  { key: 'human_overridden', label: 'human override', className: 'bg-violet-50 text-violet-700 ring-violet-600/20' },
  { key: 'escalated', label: 'escalated', className: 'bg-amber-50 text-amber-800 ring-amber-600/20' },
]

// The canonical order the ticket's first acceptance criterion asks a judge to
// be able to read: detected → decision → policy check → allocation → execution
// → webhook → reassessment → stop.
const STAGE_META: Record<string, { title: string; dot: string }> = {
  detected: { title: 'Detected', dot: 'bg-gray-400' },
  decision: { title: 'Decision + reasoning', dot: 'bg-blue-500' },
  policy_check: { title: 'Policy check', dot: 'bg-indigo-500' },
  allocation: { title: 'Budget allocation', dot: 'bg-teal-500' },
  execution: { title: 'Execution', dot: 'bg-emerald-500' },
  webhook: { title: 'Outcome webhook', dot: 'bg-sky-500' },
  reassessment: { title: 'Reassessment triggered', dot: 'bg-orange-400' },
  outcome: { title: 'Outcome', dot: 'bg-gray-800' },
}

function FlagChips({ flags }: { flags: CaseFlags }) {
  const active = FLAG_LABELS.filter((f) => flags[f.key])
  if (active.length === 0) return null
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {active.map((f) => (
        <span key={f.key} className={`rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${f.className}`}>
          {f.label}
        </span>
      ))}
    </div>
  )
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' ? value : undefined
}

function StageDetail({ stage }: { stage: TimelineStage }) {
  const d = stage.detail
  if (stage.stage === 'decision') {
    const pe = asNumber(d.point_estimate)
    const unc = asNumber(d.uncertainty)
    return (
      <div className="mt-1 space-y-1 text-xs text-gray-600">
        {pe !== undefined && (
          <p>
            estimate <span className="font-mono">{pct(pe)}</span>
            {unc !== undefined && <span className="text-gray-400"> ± {unc.toFixed(2)} band</span>}
            {d.customer_segment_proxy ? <span className="text-gray-400"> · {String(d.customer_segment_proxy)}</span> : null}
            {d.failure_reason ? <span className="text-gray-400"> · {String(d.failure_reason)}</span> : null}
          </p>
        )}
        {d.justification ? <p className="italic text-gray-700">“{String(d.justification)}”</p> : null}
      </div>
    )
  }
  if (stage.stage === 'policy_check' && d.approved === false) {
    return (
      <div className="mt-1 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
        <p>
          bound by <span className="font-mono font-semibold">{String(d.violated_constraint)}</span>
          {d.proposed_value != null && <span> — proposed value {String(d.proposed_value)}</span>}
        </p>
        {d.reason ? <p className="mt-0.5 text-red-700">{String(d.reason)}</p> : null}
      </div>
    )
  }
  if (stage.stage === 'allocation') {
    return (
      <p className="mt-1 text-xs text-gray-600">
        {String(d.reason ?? '')}
        {asNumber(d.reserved) !== undefined && (
          <span className="text-gray-400"> · reserve held {asNumber(d.reserved)! > 0 ? 'yes' : 'no'}</span>
        )}
      </p>
    )
  }
  if (stage.stage === 'execution') {
    const link = d.short_url ?? d.payment_link_id ?? d.subscription_id
    return link ? <p className="mt-1 font-mono text-xs text-gray-500">{String(link)}</p> : null
  }
  if (stage.stage === 'outcome' && d.reason) {
    return <p className="mt-1 text-xs text-gray-600">{String(d.reason)}</p>
  }
  return null
}

function Timeline({ caseId }: { caseId: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['case-timeline', caseId],
    queryFn: () => fetchCaseTimeline(caseId),
    refetchInterval: 3000,
  })

  if (isLoading) return <p className="text-sm text-gray-500">Loading timeline…</p>
  if (isError) return <p className="text-sm text-red-600">{String(error)}</p>
  if (!data) return null

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-mono text-xs text-gray-400">{data.case.id}</p>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[data.case.status]}`}>
          {data.case.status}
        </span>
        <span className="text-xs text-gray-500">{data.case.workflow_type}</span>
      </div>
      <FlagChips flags={data.case.flags} />

      <ol className="mt-4 border-l border-gray-200">
        {data.stages.map((stage, i) => {
          const meta = STAGE_META[stage.stage] ?? { title: stage.stage, dot: 'bg-gray-400' }
          return (
            <li key={i} className="relative pb-5 pl-5 last:pb-0">
              <span className={`absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full ${meta.dot}`} />
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">{meta.title}</p>
                <time className="shrink-0 font-mono text-[11px] text-gray-400">{clockTime(stage.timestamp)}</time>
              </div>
              <p className="mt-0.5 text-sm text-gray-800">{stage.label}</p>
              <StageDetail stage={stage} />
            </li>
          )
        })}
      </ol>
    </div>
  )
}

export function CaseTimelineView() {
  const { data: cases, isLoading, isError, error } = useQuery({
    queryKey: ['case-summaries'],
    queryFn: fetchCaseSummaries,
    refetchInterval: 3000,
  })
  const [picked, setPicked] = useState<string | null>(null)

  if (isLoading) return <p className="text-gray-500">Loading cases…</p>
  if (isError) return <p className="text-red-600">{String(error)}</p>
  if (!cases || cases.length === 0) {
    return (
      <p className="text-gray-500">
        No Recovery Cases yet. Run <code className="rounded bg-gray-100 px-1">uv run python -m app.demo_seed</code> to
        populate the demo.
      </p>
    )
  }

  // Derived during render (no effect): honour an explicit pick, else default to
  // the first case that shows off a demo beat, else the newest.
  const selectedId = picked ?? (cases.find((c) => Object.values(c.flags).some(Boolean)) ?? cases[0]).id

  return (
    <div className="grid gap-6 md:grid-cols-[minmax(0,18rem)_1fr]">
      <ul className="space-y-1.5">
        {cases.map((c) => (
          <li key={c.id}>
            <button
              className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                c.id === selectedId ? 'border-blue-400 bg-blue-50' : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
              onClick={() => setPicked(c.id)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-gray-500">{shortId(c.id)}</span>
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${STATUS_BADGE[c.status]}`}>
                  {c.status}
                </span>
              </div>
              <p className="mt-0.5 text-[11px] text-gray-400">{c.workflow_type}</p>
              <FlagChips flags={c.flags} />
            </button>
          </li>
        ))}
      </ul>

      <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
        {selectedId && <Timeline caseId={selectedId} />}
      </div>
    </div>
  )
}
