import type { Heatmap, Place, Plan, PlanInput } from './types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {}

/** Flattens DRF error payloads ({field: [msg]}, {detail}) into one sentence. */
function describeError(body: unknown, status: number): string {
  if (body && typeof body === 'object') {
    const obj = body as Record<string, unknown>
    if (typeof obj.detail === 'string') return obj.detail
    const parts: string[] = []
    const walk = (value: unknown, path: string) => {
      if (Array.isArray(value)) value.forEach((v) => walk(v, path))
      else if (value && typeof value === 'object')
        Object.entries(value).forEach(([k, v]) => walk(v, k === 'non_field_errors' ? path : k))
      else if (typeof value === 'string') parts.push(path ? `${path.replace('_', ' ')}: ${value}` : value)
    }
    walk(obj, '')
    if (parts.length) return parts.join(' ')
  }
  return `Request failed (${status})`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError('Network error: is the API running?')
  }
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(describeError(body, res.status))
  return body as T
}

export function geocode(q: string, signal?: AbortSignal): Promise<{ results: Place[] }> {
  return request(`/api/geocode?q=${encodeURIComponent(q)}`, { signal })
}

export function planTrip(input: PlanInput, signal?: AbortSignal): Promise<Plan> {
  return request('/api/plan', { method: 'POST', body: JSON.stringify(input), signal })
}

export function fetchHeatmap(plan: Plan, signal?: AbortSignal): Promise<Heatmap> {
  const body = {
    paths: plan.routes.map((r) => r.path),
    departure: plan.inputs.departure,
    load_lbs: plan.inputs.load_lbs,
  }
  return request('/api/heatmap', { method: 'POST', body: JSON.stringify(body), signal })
}
