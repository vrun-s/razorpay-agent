import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchCases } from './api'
import { EscalationQueue } from './EscalationQueue'
import { CaseTimelineView } from './CaseTimeline'
import { BudgetTimelineView } from './BudgetTimeline'
import { EvaluationView } from './Evaluation'

const TABS = [
  { id: 'timeline', label: 'Case Timeline', title: 'Case Timeline', blurb: 'Every step of one recovery, detected to stopped, with the constraint that bound each decision.' },
  { id: 'budget', label: 'Reserved Budget', title: 'Reserved Budget', blurb: 'The portion of the recovery budget held back for better cases still to arrive — decision by decision.' },
  { id: 'evaluation', label: 'Evaluation', title: 'Evaluation', blurb: 'Net Recovered Revenue against two baselines and the offline-optimal ceiling, with a calibration curve.' },
  { id: 'escalations', label: 'Escalations', title: 'Escalation Queue', blurb: 'Cases handed to a human — override with an intervention, or resolve directly.' },
] as const

type TabId = (typeof TABS)[number]['id']

const TAB_STORAGE_KEY = 'recovery-dashboard-tab'
const THEME_STORAGE_KEY = 'rr-theme'

function loadTab(): TabId {
  try {
    const saved = localStorage.getItem(TAB_STORAGE_KEY)
    if (saved && TABS.some((t) => t.id === saved)) return saved as TabId
  } catch {
    // localStorage unavailable (private window, blocked) — fall through.
  }
  return 'timeline'
}

function currentTheme(): 'light' | 'dark' {
  const attr = document.documentElement.dataset.theme
  if (attr === 'light' || attr === 'dark') return attr
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function ThemeToggle() {
  const [theme, setTheme] = useState<'light' | 'dark'>(currentTheme)

  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // ignore
    }
    setTheme(next)
  }

  return (
    <button
      onClick={toggle}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
      className="grid h-8 w-8 place-items-center rounded-md text-topbar-ink/70 transition hover:bg-white/10 hover:text-topbar-ink"
    >
      {theme === 'dark' ? (
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  )
}

function TopBar() {
  return (
    <header className="bg-topbar text-topbar-ink">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-6">
        <span className="flex items-center gap-2 font-extrabold tracking-tight">
          <svg viewBox="0 0 24 24" className="h-5 w-5 text-brand" fill="currentColor" aria-hidden="true">
            <path d="M16 2 6 13h5l-3 9L20 9h-6z" />
          </svg>
          Razorpay
        </span>
        <span className="hidden text-topbar-ink/30 sm:inline">/</span>
        <span className="hidden text-sm font-semibold text-topbar-ink/85 sm:inline">Revenue Recovery</span>

        <div className="ml-auto flex items-center gap-2">
          <span className="flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-semibold tracking-wide">
            <span className="h-1.5 w-1.5 rounded-full bg-ok" />
            DEMO
          </span>
          <ThemeToggle />
          <span className="grid h-8 w-8 place-items-center rounded-full bg-brand text-xs font-bold text-white">VS</span>
        </div>
      </div>
    </header>
  )
}

function EscalationsTab() {
  const { data: cases, isLoading, isError, error } = useQuery({
    queryKey: ['cases'],
    queryFn: fetchCases,
    refetchInterval: 3000,
  })

  if (isLoading) return <p className="text-muted">Loading cases…</p>
  if (isError) return <p className="text-bad">Failed to load cases: {String(error)}</p>
  return <EscalationQueue cases={cases ?? []} />
}

function App() {
  const [tab, setTab] = useState<TabId>(loadTab)
  const active = TABS.find((t) => t.id === tab) ?? TABS[0]

  const selectTab = (id: TabId) => {
    setTab(id)
    try {
      localStorage.setItem(TAB_STORAGE_KEY, id)
    } catch {
      // ignore
    }
  }

  return (
    <div className="min-h-svh bg-bg text-ink">
      <TopBar />

      <div className="mx-auto max-w-6xl px-6">
        <nav className="flex gap-1 overflow-x-auto border-b border-border">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => selectTab(t.id)}
              className={`-mb-px shrink-0 border-b-2 px-3 py-3 text-sm font-semibold transition ${
                tab === t.id
                  ? 'border-brand text-brand'
                  : 'border-transparent text-muted hover:text-ink'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <header className="pt-8">
          <p className="kicker">Track 03 — Revenue Recovery</p>
          <h1 className="mt-1 font-serif text-3xl font-medium tracking-tight text-ink">{active.title}</h1>
          <p className="mt-1.5 max-w-2xl text-sm text-muted">{active.blurb}</p>
        </header>

        <main key={tab} className="tab-fade py-7">
          {tab === 'timeline' && <CaseTimelineView />}
          {tab === 'budget' && <BudgetTimelineView />}
          {tab === 'evaluation' && <EvaluationView />}
          {tab === 'escalations' && <EscalationsTab />}
        </main>
      </div>
    </div>
  )
}

export default App
