const timeFmt = new Intl.DateTimeFormat(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })
const timeZoneFmt = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' })

export function formatTime(value: string | number | Date): string {
  return timeFmt.format(typeof value === 'number' ? new Date(value * 1000) : new Date(value))
}

export function localZone(): string {
  return timeZoneFmt.formatToParts(new Date()).find((p) => p.type === 'timeZoneName')?.value ?? ''
}

export function formatDuration(seconds: number): string {
  const totalMin = Math.round(seconds / 60)
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h ${String(m).padStart(2, '0')}m`
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`
}

export const formatMiles = (mi: number) => `${Math.round(mi).toLocaleString()} mi`

/** Value for <input type="datetime-local"> in the browser's zone. */
export function toLocalInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function nextQuarterHour(from = new Date()): Date {
  const d = new Date(from)
  d.setSeconds(0, 0)
  d.setMinutes(Math.ceil((d.getMinutes() + 1) / 15) * 15)
  return d
}
