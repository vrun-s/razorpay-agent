import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchCaseSummaries, fetchCaseTimeline, type CaseFlags, type TimelineStage } from './api'
import { STATUS_BADGE, clockTime, pct, shortId } from './format'

const FLAG_LABELS: { key: keyof CaseFlags; label: string; className: string }[] = [
  { key: 'no_action_recovered', label: 'NO_ACTION recovered', className: 'bg-ok-wash text-ok ring-ok/25' },
  { key: 'policy_rejected', label: 'policy rejection', className: 'bg-bad-wash text-bad ring-bad/25' },
  { key: 'human_overridden', label: 'human override', className: 'bg-violet-wash text-violet ring-violet/25' },
  { key: 'escalated', label: 'escalated', className: 'bg-warn-wash text-warn ring-warn/25' },
]

// The canonical order the ticket's first acceptance criterion asks a judge to
// be able to read: detected → decision → policy check → allocation → execution
// → webhook → reassessment → stop. `node` is the stepper dot's colour.
const STAGE_META: Record<string, { title: string; node: string }> = {
  detected: { title: 'Detected', node: 'bg-faint' },
  decision: { title: 'Decision + reasoning', node: 'bg-brand' },
  policy_check: { title: 'Policy check', node: 'bg-violet' },
  allocation: { title: 'Budget allocation', node: 'bg-kicker' },
  execution: { title: 'Execution', node: 'bg-ok' },
  webhook: { title: 'Outcome webhook', node: 'bg-brand' },
  reassessment: { title: 'Reassessment triggered', node: 'bg-warn' },
  outcome: { title: 'Outcome', node: 'bg-ink' },
}

function FlagChips({ flags }: { flags: CaseFlags }) {
  const active = FLAG_LABELS.filter((f) => flags[f.key])
  if (active.length === 0) return null
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {active.map((f) => (
        <span key={f.key} className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${f.className}`}>
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
      <div className="mt-1 space-y-1 text-xs text-muted">
        {pe !== undefined && (
          <p>
            estimate <span className="font-mono text-ink">{pct(pe)}</span>
            {unc !== undefined && <span className="text-faint"> ± {unc.toFixed(2)} band</span>}
            {d.customer_segment_proxy ? <span className="text-faint"> · {String(d.customer_segment_proxy)}</span> : null}
            {d.failure_reason ? <span className="text-faint"> · {String(d.failure_reason)}</span> : null}
          </p>
        )}
        {d.justification ? <p className="border-l-2 border-border pl-2 italic text-ink/80">{String(d.justification)}</p> : null}
      </div>
    )
  }
  if (stage.stage === 'policy_check' && d.approved === false) {
    return (
      <div className="mt-1.5 rounded-md border border-bad/25 bg-bad-wash px-2.5 py-2 text-xs text-bad">
        <p>
          bound by <span className="font-mono font-semibold">{String(d.violated_constraint)}</span>
          {d.proposed_value != null && <span> — proposed value {String(d.proposed_value)}</span>}
        </p>
        {d.reason ? <p className="mt-0.5 opacity-80">{String(d.reason)}</p> : null}
      </div>
    )
  }
  if (stage.stage === 'allocation') {
    return (
      <p className="mt-1 text-xs text-muted">
        {String(d.reason ?? '')}
        {asNumber(d.reserved) !== undefined && (
          <span className="text-faint"> · reserve held {asNumber(d.reserved)! > 0 ? 'yes' : 'no'}</span>
        )}
      </p>
    )
  }
  if (stage.stage === 'execution') {
    const link = d.short_url ?? d.payment_link_id ?? d.subscription_id
    return link ? <p className="mt-1 font-mono text-xs text-faint">{String(link)}</p> : null
  }
  if (stage.stage === 'outcome' && d.reason) {
    return <p className="mt-1 text-xs text-muted">{String(d.reason)}</p>
  }
  return null
}

function Timeline({ caseId }: { caseId: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['case-timeline', caseId],
    queryFn: () => fetchCaseTimeline(caseId),
    refetchInterval: 3000,
  })

  if (isLoading) return <p className="text-sm text-muted">Loading timeline…</p>
  if (isError) return <p className="text-sm text-bad">{String(error)}</p>
  if (!data) return null

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-mono text-xs text-faint">{data.case.id}</p>
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_BADGE[data.case.status]}`}>
          {data.case.status}
        </span>
        <span className="text-xs text-muted">{data.case.workflow_type}</span>
      </div>
      <FlagChips flags={data.case.flags} />

      <ol className="mt-5">
        {data.stages.map((stage, i) => {
          const meta = STAGE_META[stage.stage] ?? { title: stage.stage, node: 'bg-faint' }
          const last = i === data.stages.length - 1
          return (
            <li key={i} className="relative grid grid-cols-[1.25rem_1fr] gap-x-3 pb-5 last:pb-0">
              <div className="flex flex-col items-center">
                <span className={`mt-0.5 h-3 w-3 rounded-full ring-4 ring-surface ${meta.node}`} />
                {!last && <span className="mt-1 w-px flex-1 bg-border" />}
              </div>
              <div className="min-w-0">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">{meta.title}</p>
                  <time className="shrink-0 font-mono text-[11px] text-faint">{clockTime(stage.timestamp)}</time>
                </div>
                <p className="mt-0.5 text-sm text-ink">{stage.label}</p>
                <StageDetail stage={stage} />
              </div>
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

  if (isLoading) return <p className="text-muted">Loading cases…</p>
  if (isError) return <p className="text-bad">{String(error)}</p>
  if (!cases || cases.length === 0) {
    return (
      <p className="rounded-lg border border-warn/30 bg-warn-wash px-3 py-2.5 text-sm text-warn">
        No Recovery Cases yet. Run <span className="codechip">uv run python -m app.demo_seed</span> to populate the demo.
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
                c.id === selectedId
                  ? 'border-brand bg-brand-wash'
                  : 'border-border bg-surface hover:border-faint'
              }`}
              onClick={() => setPicked(c.id)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-muted">{shortId(c.id)}</span>
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${STATUS_BADGE[c.status]}`}>
                  {c.status}
                </span>
              </div>
              <p className="mt-0.5 text-[11px] text-faint">{c.workflow_type}</p>
              <FlagChips flags={c.flags} />
            </button>
          </li>
        ))}
      </ul>

      <div className="card self-start p-5">{selectedId && <Timeline caseId={selectedId} />}</div>
    </div>
  )
}
