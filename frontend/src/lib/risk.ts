import type { LevelKey, MilesByLevel, RiskLevel } from '../types'

export const LEVELS: { level: RiskLevel; key: LevelKey; label: string; color: string }[] = [
  { level: 0, key: 'low', label: 'Low', color: '#2fa36b' },
  { level: 1, key: 'moderate', label: 'Moderate', color: '#e8b71a' },
  { level: 2, key: 'high', label: 'High', color: '#f07c1b' },
  { level: 3, key: 'severe', label: 'Severe', color: '#d6383a' },
  { level: 4, key: 'no_travel', label: 'No Travel', color: '#7a1fa2' },
]

export const levelColor = (level: number) => LEVELS[level]?.color ?? '#888'
export const levelLabel = (level: number) => LEVELS[level]?.label ?? '—'

/** Route identity colours — chosen to stay distinct from the risk palette. */
export const ROUTE_COLORS: Record<string, string> = { A: '#2563eb', B: '#9333ea', C: '#0e7490' }
export const routeColor = (id: string) => ROUTE_COLORS[id] ?? '#64748b'

export const totalMiles = (m: MilesByLevel) => LEVELS.reduce((sum, l) => sum + m[l.key], 0)

/** Short WMO weather-code description (display only; risk uses the numbers). */
export function weatherText(code: number): string {
  if (code === 0) return 'Clear'
  if (code <= 3) return 'Cloudy'
  if (code === 45 || code === 48) return 'Fog'
  if (code >= 51 && code <= 57) return 'Drizzle'
  if (code >= 61 && code <= 67) return code >= 66 ? 'Freezing rain' : 'Rain'
  if (code >= 71 && code <= 77) return 'Snow'
  if (code >= 80 && code <= 82) return 'Showers'
  if (code === 85 || code === 86) return 'Snow showers'
  if (code >= 95) return 'Thunderstorm'
  return '—'
}
