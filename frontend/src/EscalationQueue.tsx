import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { overrideCase, resolveCase, type CaseHistoryEntry, type Intervention, type RecoveryCase, type WorkflowType } from './api'

const WORKFLOW_INTERVENTIONS: Record<WorkflowType, Intervention[]> = {
  failed_payment: ['payment_retry', 'no_action'],
  halted_subscription: ['resume_charge', 'no_action'],
}

function reasoningFor(recoveryCase: RecoveryCase): { justification?: string; escalationReason?: string } {
  const decisions = recoveryCase.history.filter((entry): entry is CaseHistoryEntry & { data: { justification?: string } } =>
    entry.entry_type === 'decision',
  )
  const escalation = recoveryCase.history.find((entry) => entry.entry_type === 'case_escalated')
  return {
    justification: decisions.at(-1)?.data.justification as string | undefined,
    escalationReason: escalation?.data.reason as string | undefined,
  }
}

const FIELD = 'rounded-md border border-border bg-surface px-2 py-1 text-sm text-ink'

function EscalationCard({ recoveryCase }: { recoveryCase: RecoveryCase }) {
  const queryClient = useQueryClient()
  const interventions = WORKFLOW_INTERVENTIONS[recoveryCase.workflow_type]
  const [intervention, setIntervention] = useState<Intervention>(interventions[0])
  const [resolution, setResolution] = useState<'recovered' | 'stopped'>('recovered')
  const [reason, setReason] = useState('')
  const { justification, escalationReason } = reasoningFor(recoveryCase)

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['cases'] })

  const overrideMutation = useMutation({
    mutationFn: () => overrideCase(recoveryCase.id, intervention),
    onSuccess: invalidate,
  })
  const resolveMutation = useMutation({
    mutationFn: () => resolveCase(recoveryCase.id, resolution, reason),
    onSuccess: invalidate,
  })

  return (
    <div className="rounded-xl border border-warn/40 bg-warn-wash p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-mono text-xs text-faint">{recoveryCase.id}</p>
          <p className="text-sm text-muted">{recoveryCase.workflow_type}</p>
        </div>
        <span className="rounded-full bg-warn/15 px-2.5 py-1 text-xs font-semibold text-warn">escalated</span>
      </div>

      {(justification || escalationReason) && (
        <div className="mt-3 rounded-md border border-border bg-surface p-2.5 text-sm text-ink">
          {justification && <p>{justification}</p>}
          {escalationReason && <p className="mt-1 text-warn">Escalated: {escalationReason}</p>}
        </div>
      )}

      <details className="mt-3">
        <summary className="cursor-pointer text-xs font-semibold text-muted">
          Full Case History ({recoveryCase.history.length})
        </summary>
        <ul className="mt-2 divide-y divide-border border-t border-border pt-2">
          {recoveryCase.history.map((entry) => (
            <li key={entry.id} className="flex items-start gap-3 py-1.5 text-sm">
              <span className="mt-0.5 shrink-0 rounded bg-surface px-1.5 py-0.5 font-mono text-xs text-muted">
                {entry.entry_type}
              </span>
              <span className="text-ink/80">{entry.summary}</span>
            </li>
          ))}
        </ul>
      </details>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-md border border-border bg-surface p-3">
          <p className="text-xs font-semibold text-muted">Override with an Intervention</p>
          <div className="mt-2 flex gap-2">
            <select className={`flex-1 ${FIELD}`} value={intervention} onChange={(e) => setIntervention(e.target.value as Intervention)}>
              {interventions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            <button
              className="rounded-md bg-brand px-3 py-1 text-sm font-semibold text-white transition hover:bg-brand-strong disabled:opacity-50"
              disabled={overrideMutation.isPending}
              onClick={() => overrideMutation.mutate()}
            >
              Override
            </button>
          </div>
          {overrideMutation.isError && <p className="mt-1 text-xs text-bad">{String(overrideMutation.error)}</p>}
        </div>

        <div className="rounded-md border border-border bg-surface p-3">
          <p className="text-xs font-semibold text-muted">Manually resolve</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <select className={FIELD} value={resolution} onChange={(e) => setResolution(e.target.value as 'recovered' | 'stopped')}>
              <option value="recovered">recovered</option>
              <option value="stopped">stopped</option>
            </select>
            <input
              className={`min-w-0 flex-1 ${FIELD}`}
              placeholder="Reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <button
              className="rounded-md border border-border bg-surface-2 px-3 py-1 text-sm font-semibold text-ink transition hover:border-faint disabled:opacity-50"
              disabled={resolveMutation.isPending || !reason.trim()}
              onClick={() => resolveMutation.mutate()}
            >
              Resolve
            </button>
          </div>
          {resolveMutation.isError && <p className="mt-1 text-xs text-bad">{String(resolveMutation.error)}</p>}
        </div>
      </div>
    </div>
  )
}

export function EscalationQueue({ cases }: { cases: RecoveryCase[] }) {
  const escalated = cases.filter((c) => c.status === 'escalated')

  return (
    <section>
      {escalated.length === 0 && <p className="text-sm text-muted">No escalated cases right now.</p>}

      <div className="space-y-4">
        {escalated.map((recoveryCase) => (
          <EscalationCard key={recoveryCase.id} recoveryCase={recoveryCase} />
        ))}
      </div>
    </section>
  )
}
