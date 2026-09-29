// Robust ISO timestamp parsing + IST display helpers.
//
// The API stores UTC ISO strings. Most arrive with an explicit offset
// ("...+00:00" or "...Z"), but any without one must be treated as UTC —
// appending "Z" (the old approach) produced "...+00:00Z" → Invalid Date.

const IST_OPTIONS = {
  timeZone: 'Asia/Kolkata',
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: true,
}

/** Parse an API timestamp into a Date, or null when absent/unparseable. */
export function parseWhen(value) {
  if (!value || typeof value !== 'string') return null
  const looksUtc = value.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(value)
  const normalized = looksUtc ? value : `${value}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

/** "27 Sep 2026, 09:41 pm IST" */
export function formatIst(value) {
  const date = parseWhen(value)
  if (!date) return '—'
  return `${date.toLocaleString('en-IN', IST_OPTIONS)} IST`
}

/** "27 Sep 2026" in IST */
export function formatIstDate(value) {
  const date = parseWhen(value)
  if (!date) return '—'
  return date.toLocaleDateString('en-IN', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: 'short',
    day: '2-digit',
  })
}

/** Whole seconds between two API timestamps (null-safe). */
export function secondsBetween(start, end) {
  const a = parseWhen(start)
  const b = parseWhen(end)
  if (!a || !b) return null
  return Math.max(0, Math.round((b - a) / 1000))
}

/** Today's date (YYYY-MM-DD) in IST. */
export function istTodayYmd(now = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now)
}

/** [start, end) Date pair covering today's IST calendar day, in UTC terms. */
export function istDayRange(now = new Date()) {
  const ymd = istTodayYmd(now)
  const start = new Date(`${ymd}T00:00:00+05:30`)
  const end = new Date(start.getTime() + 24 * 60 * 60 * 1000)
  return { start, end, ymd }
}

/** True when an API timestamp falls inside today's IST calendar day. */
export function isSameIstDay(value, now = new Date()) {
  if (!value) return false
  const date = parseWhen(value)
  if (!date) return false
  return istTodayYmd(date) === istTodayYmd(now)
}
