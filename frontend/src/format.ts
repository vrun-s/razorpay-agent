/** paise (smallest currency unit, as everything server-side stores) -> "₹1,23,456". */
export function rupees(paise: number): string {
  return `₹${Math.round(paise / 100).toLocaleString('en-IN')}`
}

export function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…` : id
}

export function clockTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function pct(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`
}

/** Tailwind badge classes per Recovery Case status — shared by every view that renders one. */
export const STATUS_BADGE: Record<'open' | 'recovered' | 'stopped' | 'escalated', string> = {
  open: 'bg-blue-100 text-blue-800',
  recovered: 'bg-green-100 text-green-800',
  stopped: 'bg-gray-100 text-gray-700',
  escalated: 'bg-amber-100 text-amber-800',
}
