const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export type WorkflowType = 'failed_payment' | 'halted_subscription'
export type CaseStatus = 'open' | 'recovered' | 'stopped' | 'escalated'
export type EventSource = 'real' | 'simulated'
export type CaseHistoryEntryType = 'case_created' | 'decision' | 'policy_check' | 'execution'

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
