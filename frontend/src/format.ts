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

/** Badge classes per Recovery Case status — shared by every view that renders one. */
export const STATUS_BADGE: Record<'open' | 'recovered' | 'stopped' | 'escalated', string> = {
  open: 'bg-brand-wash text-brand',
  recovered: 'bg-ok-wash text-ok',
  stopped: 'bg-surface-2 text-muted',
  escalated: 'bg-warn-wash text-warn',
}
