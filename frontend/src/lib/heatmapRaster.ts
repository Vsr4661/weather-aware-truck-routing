/**
 * Heatmap frames as images.
 *
 * The backend grid is regular in Web-Mercator space, so one hour of data maps
 * 1:1 onto a cols x rows bitmap that MapLibre can stretch over the bbox as an
 * image source. Each frame is painted once, upscaled with bilinear smoothing
 * (soft cell edges and a feathered corridor boundary), and cached as a data
 * URL, so scrubbing the 0-48 h slider is only an image swap.
 */
import type { HeatLayer, Heatmap } from '../types'
import { LEVELS } from './risk'

type RGBA = [number, number, number, number]
type Stop = { at: number; color: string; alpha: number; label: string }

const hex = (h: string): [number, number, number] => [
  parseInt(h.slice(1, 3), 16),
  parseInt(h.slice(3, 5), 16),
  parseInt(h.slice(5, 7), 16),
]

/** Colour ramps whose stops sit on the spec's risk thresholds. */
export const RAMPS: Record<Exclude<HeatLayer, 'risk'>, { unit: string; stops: Stop[] }> = {
  wind: {
    unit: 'mph',
    stops: [
      { at: 10, color: '#7dd3fc', alpha: 0, label: '10' },
      { at: 25, color: '#e8b71a', alpha: 0.45, label: '25' },
      { at: 35, color: '#f07c1b', alpha: 0.6, label: '35' },
      { at: 45, color: '#d6383a', alpha: 0.72, label: '45' },
      { at: 55, color: '#7a1fa2', alpha: 0.82, label: '55+' },
    ],
  },
  gust: {
    unit: 'mph',
    stops: [
      { at: 15, color: '#7dd3fc', alpha: 0, label: '15' },
      { at: 25, color: '#e8b71a', alpha: 0.4, label: '25' },
      { at: 35, color: '#f07c1b', alpha: 0.55, label: '35' },
      { at: 45, color: '#d6383a', alpha: 0.7, label: '45' },
      { at: 55, color: '#7a1fa2', alpha: 0.8, label: '55+' },
    ],
  },
  rain: {
    unit: 'in/hr',
    stops: [
      { at: 0.005, color: '#93c5fd', alpha: 0, label: '0' },
      { at: 0.1, color: '#3b82f6', alpha: 0.5, label: '0.10' },
      { at: 0.25, color: '#1d4ed8', alpha: 0.62, label: '0.25' },
      { at: 0.5, color: '#4c1d95', alpha: 0.72, label: '0.50' },
      { at: 1.0, color: '#be185d', alpha: 0.82, label: '1.0+' },
    ],
  },
  snow: {
    unit: 'in/hr',
    stops: [
      { at: 0.02, color: '#e0f2fe', alpha: 0, label: '0' },
      { at: 0.5, color: '#a5b4fc', alpha: 0.5, label: '0.5' },
      { at: 1.0, color: '#818cf8', alpha: 0.62, label: '1' },
      { at: 2.0, color: '#6d28d9', alpha: 0.72, label: '2' },
      { at: 3.0, color: '#be185d', alpha: 0.82, label: '3+' },
    ],
  },
}

const RISK_ALPHA = [0.12, 0.45, 0.6, 0.72, 0.8]

function rampColor(stops: Stop[], v: number): RGBA {
  if (v <= stops[0].at) return [...hex(stops[0].color), 0]
  for (let i = 1; i < stops.length; i++) {
    if (v <= stops[i].at) {
      const a = stops[i - 1]
      const b = stops[i]
      const t = (v - a.at) / (b.at - a.at)
      const ca = hex(a.color)
      const cb = hex(b.color)
      return [
        ca[0] + (cb[0] - ca[0]) * t,
        ca[1] + (cb[1] - ca[1]) * t,
        ca[2] + (cb[2] - ca[2]) * t,
        a.alpha + (b.alpha - a.alpha) * t,
      ]
    }
  }
  const last = stops[stops.length - 1]
  return [...hex(last.color), last.alpha]
}

export function colorFor(layer: HeatLayer, v: number): RGBA {
  if (layer === 'risk') return [...hex(LEVELS[v]?.color ?? '#888888'), RISK_ALPHA[v] ?? 0]
  return rampColor(RAMPS[layer].stops, v)
}

const UPSCALE = 6

export class HeatmapFrames {
  private cache = new Map<string, string>()
  private small: HTMLCanvasElement
  private big: HTMLCanvasElement
  private readonly heatmap: Heatmap
  private readonly cellPos: Map<number, number>

  constructor(heatmap: Heatmap) {
    this.heatmap = heatmap
    this.small = document.createElement('canvas')
    this.small.width = heatmap.cols
    this.small.height = heatmap.rows
    this.big = document.createElement('canvas')
    this.big.width = heatmap.cols * UPSCALE
    this.big.height = heatmap.rows * UPSCALE
    this.cellPos = new Map(heatmap.cells.map((flat, pos) => [flat, pos]))
  }

  /** Image corners for a MapLibre image source: TL, TR, BR, BL. */
  get coordinates(): [[number, number], [number, number], [number, number], [number, number]] {
    const [w, s, e, n] = this.heatmap.bbox
    return [
      [w, n],
      [e, n],
      [e, s],
      [w, s],
    ]
  }

  frame(layer: HeatLayer, hour: number): string {
    const key = `${layer}:${hour}`
    const hit = this.cache.get(key)
    if (hit) return hit
    const { cols, rows, cells, layers } = this.heatmap
    const values = layers[layer][hour]
    const sctx = this.small.getContext('2d')!
    const img = sctx.createImageData(cols, rows)
    for (let k = 0; k < cells.length; k++) {
      const [r, g, b, a] = colorFor(layer, values[k])
      const o = cells[k] * 4
      img.data[o] = r
      img.data[o + 1] = g
      img.data[o + 2] = b
      img.data[o + 3] = Math.round(a * 255)
    }
    sctx.putImageData(img, 0, 0)
    const bctx = this.big.getContext('2d')!
    bctx.clearRect(0, 0, this.big.width, this.big.height)
    bctx.imageSmoothingEnabled = true
    bctx.imageSmoothingQuality = 'high'
    bctx.drawImage(this.small, 0, 0, this.big.width, this.big.height)
    const url = this.big.toDataURL('image/png')
    this.cache.set(key, url)
    return url
  }

  /** Paint remaining frames during idle time so playback never stalls. */
  warm(layer: HeatLayer, isCancelled: () => boolean): void {
    let hour = 0
    const step = (deadline?: IdleDeadline) => {
      while (hour < this.heatmap.times.length && !isCancelled()) {
        this.frame(layer, hour++)
        if (deadline && deadline.timeRemaining() < 4) break
      }
      if (hour < this.heatmap.times.length && !isCancelled()) schedule(step)
    }
    const schedule = (fn: (d?: IdleDeadline) => void) =>
      typeof window.requestIdleCallback === 'function' ? window.requestIdleCallback(fn) : setTimeout(fn, 16)
    schedule(step)
  }

  /** Index into a frame's value array for a map position, or -1 outside the corridor. */
  cellAt(lng: number, lat: number): number {
    const [w, s, e, n] = this.heatmap.bbox
    if (lng < w || lng > e || lat < s || lat > n) return -1
    const merc = (d: number) => Math.log(Math.tan(Math.PI / 4 + (d * Math.PI) / 360))
    const col = Math.floor(((lng - w) / (e - w)) * this.heatmap.cols)
    const row = Math.floor(((merc(n) - merc(lat)) / (merc(n) - merc(s))) * this.heatmap.rows)
    return this.cellPos.get(row * this.heatmap.cols + col) ?? -1
  }
}
