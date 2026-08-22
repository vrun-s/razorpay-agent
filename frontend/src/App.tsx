import { useQuery } from '@tanstack/react-query'
import { fetchCases, type CaseHistoryEntry, type RecoveryCase } from './api'

const STATUS_STYLES: Record<RecoveryCase['status'], string> = {
  open: 'bg-blue-100 text-blue-800',
  recovered: 'bg-green-100 text-green-800',
  stopped: 'bg-gray-100 text-gray-700',
  escalated: 'bg-amber-100 text-amber-800',
}

function HistoryEntryRow({ entry }: { entry: CaseHistoryEntry }) {
  return (
    <li className="flex items-start gap-3 py-1.5 text-sm">
      <span className="mt-0.5 shrink-0 rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-500">
        {entry.entry_type}
      </span>
      <span className="text-gray-700">{entry.summary}</span>
    </li>
  )
}

function CaseCard({ recoveryCase }: { recoveryCase: RecoveryCase }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-mono text-xs text-gray-400">{recoveryCase.id}</p>
          <p className="text-sm text-gray-600">{recoveryCase.workflow_type}</p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${STATUS_STYLES[recoveryCase.status]}`}>
          {recoveryCase.status}
        </span>
      </div>
      <ul className="mt-3 divide-y divide-gray-100 border-t border-gray-100 pt-2">
        {recoveryCase.history.map((entry) => (
          <HistoryEntryRow key={entry.id} entry={entry} />
        ))}
      </ul>
    </div>
  )
}

function App() {
  const { data: cases, isLoading, isError, error } = useQuery({
    queryKey: ['cases'],
    queryFn: fetchCases,
    refetchInterval: 3000,
  })

  return (
    <div className="mx-auto min-h-svh max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-semibold text-gray-900">Recovery Cases</h1>
      <p className="mt-1 text-sm text-gray-500">Polling every 3s.</p>

      {isLoading && <p className="mt-8 text-gray-500">Loading cases…</p>}
      {isError && <p className="mt-8 text-red-600">Failed to load cases: {String(error)}</p>}
      {cases && cases.length === 0 && (
        <p className="mt-8 text-gray-500">No Recovery Cases yet. POST a synthetic payment.failed payload to create one.</p>
      )}

      <div className="mt-6 space-y-4">
        {cases?.map((recoveryCase) => (
          <CaseCard key={recoveryCase.id} recoveryCase={recoveryCase} />
        ))}
      </div>
    </div>
  )
}

export default App
