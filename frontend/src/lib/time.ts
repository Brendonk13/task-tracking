const UNITS: { unit: Intl.RelativeTimeFormatUnit; ms: number }[] = [
  { unit: "year", ms: 365 * 24 * 60 * 60 * 1000 },
  { unit: "month", ms: 30 * 24 * 60 * 60 * 1000 },
  { unit: "week", ms: 7 * 24 * 60 * 60 * 1000 },
  { unit: "day", ms: 24 * 60 * 60 * 1000 },
  { unit: "hour", ms: 60 * 60 * 1000 },
  { unit: "minute", ms: 60 * 1000 },
  { unit: "second", ms: 1000 },
]

const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" })

/**
 * Formats an ISO timestamp relative to `now` (default: the current clock) in the largest
 * unit that fits, e.g. "2 hours ago", "in 3 days", "now".
 */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const diff = new Date(iso).getTime() - now
  if (Number.isNaN(diff)) return iso
  const magnitude = Math.abs(diff)
  const match = UNITS.find(({ ms }) => magnitude >= ms) ?? UNITS[UNITS.length - 1]!
  return formatter.format(Math.trunc(diff / match.ms), match.unit)
}
