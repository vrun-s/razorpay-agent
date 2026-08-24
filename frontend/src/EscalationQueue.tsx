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
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-mono text-xs text-gray-400">{recoveryCase.id}</p>
          <p className="text-sm text-gray-600">{recoveryCase.workflow_type}</p>
        </div>
        <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-800">escalated</span>
      </div>

      {(justification || escalationReason) && (
        <div className="mt-3 rounded border border-amber-200 bg-white p-2 text-sm text-gray-700">
          {justification && <p>{justification}</p>}
          {escalationReason && <p className="mt-1 text-amber-800">Escalated: {escalationReason}</p>}
        </div>
      )}

      <details className="mt-3">
        <summary className="cursor-pointer text-xs font-medium text-gray-500">Full Case History ({recoveryCase.history.length})</summary>
        <ul className="mt-2 divide-y divide-amber-100 border-t border-amber-100 pt-2">
          {recoveryCase.history.map((entry) => (
            <li key={entry.id} className="flex items-start gap-3 py-1.5 text-sm">
              <span className="mt-0.5 shrink-0 rounded bg-white px-1.5 py-0.5 font-mono text-xs text-gray-500">
                {entry.entry_type}
              </span>
              <span className="text-gray-700">{entry.summary}</span>
            </li>
          ))}
        </ul>
      </details>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded border border-gray-200 bg-white p-3">
          <p className="text-xs font-medium text-gray-500">Override with an Intervention</p>
          <div className="mt-2 flex gap-2">
            <select
              className="flex-1 rounded border border-gray-300 px-2 py-1 text-sm"
              value={intervention}
              onChange={(e) => setIntervention(e.target.value as Intervention)}
            >
              {interventions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            <button
              className="rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              disabled={overrideMutation.isPending}
              onClick={() => overrideMutation.mutate()}
            >
              Override
            </button>
          </div>
          {overrideMutation.isError && <p className="mt-1 text-xs text-red-600">{String(overrideMutation.error)}</p>}
        </div>

        <div className="rounded border border-gray-200 bg-white p-3">
          <p className="text-xs font-medium text-gray-500">Manually resolve</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <select
              className="rounded border border-gray-300 px-2 py-1 text-sm"
              value={resolution}
              onChange={(e) => setResolution(e.target.value as 'recovered' | 'stopped')}
            >
              <option value="recovered">recovered</option>
              <option value="stopped">stopped</option>
            </select>
            <input
              className="min-w-0 flex-1 rounded border border-gray-300 px-2 py-1 text-sm"
              placeholder="Reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <button
              className="rounded bg-gray-700 px-3 py-1 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
              disabled={resolveMutation.isPending || !reason.trim()}
              onClick={() => resolveMutation.mutate()}
            >
              Resolve
            </button>
          </div>
          {resolveMutation.isError && <p className="mt-1 text-xs text-red-600">{String(resolveMutation.error)}</p>}
        </div>
      </div>
    </div>
  )
}

export function EscalationQueue({ cases }: { cases: RecoveryCase[] }) {
  const escalated = cases.filter((c) => c.status === 'escalated')

  return (
    <section className="mb-8">
      <h2 className="text-lg font-semibold text-gray-900">Escalation Queue</h2>
      <p className="mt-1 text-sm text-gray-500">Cases flagged for human review — override with an Intervention, or resolve directly.</p>

      {escalated.length === 0 && <p className="mt-3 text-sm text-gray-500">No escalated cases right now.</p>}

      <div className="mt-3 space-y-4">
        {escalated.map((recoveryCase) => (
          <EscalationCard key={recoveryCase.id} recoveryCase={recoveryCase} />
        ))}
      </div>
    </section>
  )
}
