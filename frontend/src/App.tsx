import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchCases } from './api'
import { EscalationQueue } from './EscalationQueue'
import { CaseTimelineView } from './CaseTimeline'
import { BudgetTimelineView } from './BudgetTimeline'
import { EvaluationView } from './Evaluation'

const TABS = [
  { id: 'timeline', label: 'Case Timeline' },
  { id: 'budget', label: 'Reserved Budget' },
  { id: 'evaluation', label: 'Evaluation' },
  { id: 'escalations', label: 'Escalations' },
] as const

type TabId = (typeof TABS)[number]['id']

const STORAGE_KEY = 'recovery-dashboard-tab'

function loadTab(): TabId {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && TABS.some((t) => t.id === saved)) return saved as TabId
  } catch {
    // localStorage unavailable (private window, blocked) — fall through.
  }
  return 'timeline'
}

function EscalationsTab() {
  const { data: cases, isLoading, isError, error } = useQuery({
    queryKey: ['cases'],
    queryFn: fetchCases,
    refetchInterval: 3000,
  })

  if (isLoading) return <p className="text-gray-500">Loading cases…</p>
  if (isError) return <p className="text-red-600">Failed to load cases: {String(error)}</p>
  return <EscalationQueue cases={cases ?? []} />
}

function App() {
  const [tab, setTab] = useState<TabId>(loadTab)

  const selectTab = (id: TabId) => {
    setTab(id)
    try {
      localStorage.setItem(STORAGE_KEY, id)
    } catch {
      // ignore
    }
  }

  return (
    <div className="mx-auto min-h-svh max-w-5xl px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold text-gray-900">Revenue Recovery — Observability</h1>
        <p className="mt-1 text-sm text-gray-500">
          The agent's decisions, the reserve it holds back, and how it scores against the baselines.
        </p>
      </header>

      <nav className="mt-6 flex gap-1 border-b border-gray-200">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => selectTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition ${
              tab === t.id
                ? 'border-blue-600 text-blue-700'
                : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="mt-6">
        {tab === 'timeline' && <CaseTimelineView />}
        {tab === 'budget' && <BudgetTimelineView />}
        {tab === 'evaluation' && <EvaluationView />}
        {tab === 'escalations' && <EscalationsTab />}
      </main>
    </div>
  )
}

export default App
