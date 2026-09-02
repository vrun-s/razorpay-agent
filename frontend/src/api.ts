// Same-origin by default: the backend serves this bundle (ADR-0015 one-port
// collapse), and `vite dev` proxies the API prefixes to :8000 (vite.config.ts).
// Override with VITE_API_BASE_URL only for a split deployment.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export type WorkflowType = 'failed_payment' | 'halted_subscription'
export type CaseStatus = 'open' | 'recovered' | 'stopped' | 'escalated'
export type EventSource = 'real' | 'simulated'
export type Intervention = 'payment_retry' | 'resume_charge' | 'no_action'
export type CaseHistoryEntryType =
  | 'case_created'
  | 'decision'
  | 'policy_check'
  | 'allocation_check'
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

export interface RuntimeConfig {
  /** True on the public hosted instance: the write endpoints return 403 and
   * their controls should be hidden (ADR-0015). */
  demo_readonly: boolean
}

export async function fetchConfig(): Promise<RuntimeConfig> {
  const response = await fetch(`${API_BASE_URL}/config`)
  if (!response.ok) {
    throw new Error(`Failed to fetch config: ${response.status}`)
  }
  return response.json()
}

export async function fetchCases(): Promise<RecoveryCase[]> {
  const response = await fetch(`${API_BASE_URL}/cases`)
  if (!response.ok) {
    throw new Error(`Failed to fetch cases: ${response.status}`)
  }
  return response.json()
}

// -- Ticket 18: dashboard observability views --------------------------------

export interface BudgetSnapshot {
  timestamp: string
  case_id: string
  funded: boolean
  reason: string
  spent: number
  available: number
  reserved: number
}

export interface CaseFlags {
  no_action_recovered: boolean
  policy_rejected: boolean
  human_overridden: boolean
  escalated: boolean
}

export interface CaseSummary {
  id: string
  workflow_type: WorkflowType
  status: CaseStatus
  source: EventSource
  created_at: string
  flags: CaseFlags
}

export type TimelineStageName =
  | 'detected'
  | 'decision'
  | 'policy_check'
  | 'allocation'
  | 'execution'
  | 'reassessment'
  | 'outcome'

export interface TimelineStage {
  stage: TimelineStageName | string
  label: string
  timestamp: string
  entry_type: string
  detail: Record<string, unknown>
}

export interface CaseTimeline {
  case: CaseSummary
  stages: TimelineStage[]
}

export interface EvaluationArm {
  total_nrr: number
  case_count: number
  recovered_count: number
}

export interface EvaluationBaseline {
  baseline_name: string
  incremental_nrr: number
  ci_lower: number
  ci_upper: number
}

export interface CalibrationBucket {
  bucket_low: number
  bucket_high: number
  mean_predicted: number
  observed_rate: number
  count: number
}

export interface EvaluationReport {
  run_seed: number
  workflow_type: string
  split?: string
  arms: Record<string, EvaluationArm>
  baselines: EvaluationBaseline[]
  pct_of_offline_optimal: number
  calibration: CalibrationBucket[]
}

export async function fetchBudgetTimeline(): Promise<BudgetSnapshot[]> {
  const response = await fetch(`${API_BASE_URL}/budget/timeline`)
  if (!response.ok) throw new Error(`Failed to fetch budget timeline: ${response.status}`)
  return response.json()
}

export async function fetchCaseSummaries(): Promise<CaseSummary[]> {
  const response = await fetch(`${API_BASE_URL}/observability/cases`)
  if (!response.ok) throw new Error(`Failed to fetch case summaries: ${response.status}`)
  return response.json()
}

export async function fetchCaseTimeline(caseId: string): Promise<CaseTimeline> {
  const response = await fetch(`${API_BASE_URL}/observability/cases/${caseId}/timeline`)
  if (!response.ok) throw new Error(`Failed to fetch case timeline: ${response.status}`)
  return response.json()
}

/** Resolves to null when the artifact has not been generated yet (HTTP 404). */
export async function fetchEvaluationReport(): Promise<EvaluationReport | null> {
  const response = await fetch(`${API_BASE_URL}/evaluation/report`)
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`Failed to fetch evaluation report: ${response.status}`)
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
