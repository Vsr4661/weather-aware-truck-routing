import type { LngLat, Route } from '../types'

/** Segment index i and fraction t such that x lies between xs[i] and xs[i+1]. */
function locate(xs: number[], x: number): { i: number; t: number } {
  const last = xs.length - 1
  if (x <= xs[0]) return { i: 0, t: 0 }
  if (x >= xs[last]) return { i: Math.max(0, last - 1), t: 1 }
  let lo = 0
  let hi = last
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (xs[mid] <= x) lo = mid
    else hi = mid - 1
  }
  const span = xs[lo + 1] - xs[lo]
  return { i: lo, t: span ? (x - xs[lo]) / span : 0 }
}

function pointAt(path: LngLat[], i: number, t: number): LngLat {
  const a = path[i]
  const b = path[Math.min(i + 1, path.length - 1)]
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}

/** Where the truck is `elapsed` seconds after departure (parks during HOS stops). */
export function positionAt(route: Route, elapsed: number): { point: LngLat; mile: number } {
  const { i, t } = locate(route.path_s, elapsed)
  const m = route.path_miles
  const mile = m[i] + (m[Math.min(i + 1, m.length - 1)] - m[i]) * t
  return { point: pointAt(route.path, i, t), mile }
}

/** Sub-path between two mile marks, for drawing risk-coloured stretches. */
export function slicePath(route: Route, fromMile: number, toMile: number): LngLat[] {
  const { path, path_miles: miles } = route
  const start = locate(miles, fromMile)
  const end = locate(miles, toMile)
  const out: LngLat[] = [pointAt(path, start.i, start.t)]
  for (let k = start.i + 1; k <= end.i; k++) {
    if (miles[k] > fromMile && miles[k] < toMile) out.push(path[k])
  }
  out.push(pointAt(path, end.i, end.t))
  return out
}
