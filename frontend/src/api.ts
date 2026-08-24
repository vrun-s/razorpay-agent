const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export type WorkflowType = 'failed_payment' | 'halted_subscription'
export type CaseStatus = 'open' | 'recovered' | 'stopped' | 'escalated'
export type EventSource = 'real' | 'simulated'
export type Intervention = 'payment_retry' | 'resume_charge' | 'no_action'
export type CaseHistoryEntryType =
  | 'case_created'
  | 'decision'
  | 'policy_check'
  | 'execution'
  | 'reassessment_triggered'
  | 'case_recovered'
  | 'case_stopped'
  | 'case_escalated'

export interface CaseHistoryEntry {
  id: number
  created_at: string
  entry_type: CaseHistoryEntryType
  summary: string
  data: Record<string, unknown>
}

export interface RecoveryCase {
  id: string
  workflow_type: WorkflowType
  status: CaseStatus
  source: EventSource
  created_at: string
  history: CaseHistoryEntry[]
}

export async function fetchCases(): Promise<RecoveryCase[]> {
  const response = await fetch(`${API_BASE_URL}/cases`)
  if (!response.ok) {
    throw new Error(`Failed to fetch cases: ${response.status}`)
  }
  return response.json()
}

export async function overrideCase(caseId: string, intervention: Intervention): Promise<RecoveryCase> {
  const response = await fetch(`${API_BASE_URL}/cases/${caseId}/override`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ intervention }),
  })
  if (!response.ok) {
    throw new Error(`Failed to override case: ${response.status}`)
  }
  return response.json()
}

export async function resolveCase(
  caseId: string,
  outcome: 'recovered' | 'stopped',
  reason: string,
): Promise<RecoveryCase> {
  const response = await fetch(`${API_BASE_URL}/cases/${caseId}/resolve`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ outcome, reason }),
  })
  if (!response.ok) {
    throw new Error(`Failed to resolve case: ${response.status}`)
  }
  return response.json()
}
