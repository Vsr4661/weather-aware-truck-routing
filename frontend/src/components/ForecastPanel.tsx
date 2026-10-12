import { useEffect } from 'react'
import { RAMPS, colorFor } from '../lib/heatmapRaster'
import { formatTime } from '../lib/format'
import { LEVELS, levelColor, levelLabel, routeColor } from '../lib/risk'
import { positionAt } from '../lib/route'
import type { HeatLayer, Heatmap, Route } from '../types'

const LAYERS: { id: HeatLayer; label: string }[] = [
  { id: 'risk', label: 'Risk' },
  { id: 'wind', label: 'Wind' },
  { id: 'gust', label: 'Gusts' },
  { id: 'rain', label: 'Rain' },
  { id: 'snow', label: 'Snow' },
]

export const MAX_HOUR = 48

interface Props {
  heatmap: Heatmap | null
  heatLoading: boolean
  heatError: string | null
  layer: HeatLayer
  onLayer: (l: HeatLayer) => void
  visible: boolean
  onVisible: (v: boolean) => void
  hour: number
  onHour: (h: number | ((h: number) => number)) => void
  playing: boolean
  onPlaying: (p: boolean) => void
  baseTime: number // unix seconds of hour 0
  departureTs: number
  hoverCell: number
  route: Route | null
}

function Legend({ layer }: { layer: HeatLayer }) {
  if (layer === 'risk') {
    return (
      <div className="legend">
        {LEVELS.map((l) => (
          <span key={l.key}>
            <i style={{ background: l.color }} />
            {l.label}
          </span>
        ))}
      </div>
    )
  }
  const ramp = RAMPS[layer]
  const lo = ramp.stops[0].at
  const hi = ramp.stops[ramp.stops.length - 1].at
  const gradient = Array.from({ length: 12 }, (_, i) => {
    const [r, g, b, a] = colorFor(layer, lo + ((hi - lo) * i) / 11)
    return `rgba(${r | 0},${g | 0},${b | 0},${Math.max(a, 0.08)})`
  }).join(',')
  return (
    <div className="legend legend-ramp">
      <div className="ramp" style={{ background: `linear-gradient(90deg, ${gradient})` }} />
      <div className="ramp-labels">
        {ramp.stops.map((s) => (
          <span key={s.at} style={{ left: `${((s.at - lo) / (hi - lo)) * 100}%` }}>
            {s.label}
          </span>
        ))}
        <span className="unit">{ramp.unit}</span>
      </div>
    </div>
  )
}

export default function ForecastPanel(p: Props) {
  const { heatmap, hour, onHour, playing, onPlaying } = p

  useEffect(() => {
    if (!playing) return
    const id = window.setInterval(() => onHour((h) => (h >= MAX_HOUR ? 0 : h + 1)), 450)
    return () => window.clearInterval(id)
  }, [playing, onHour])

  const t = p.baseTime + hour * 3600
  const elapsed = t - p.departureTs
  const values = heatmap?.layers
  const cell = p.hoverCell
  const truck = p.route ? positionAt(p.route, elapsed) : null
  const truckState = !p.route
    ? ''
    : elapsed < 0
      ? 'not departed'
      : elapsed > p.route.trip_s
        ? 'arrived'
        : `mile ${truck!.mile.toFixed(0)} of ${p.route.distance_mi.toFixed(0)}`

  return (
    <section className="forecast" aria-label="Weather forecast timeline">
      <div className="fc-top">
        <div className="fc-time">
          <b>{formatTime(t)}</b>
          <span className="muted"> · departure +{hour} h</span>
        </div>
        <div className="segmented small" role="radiogroup" aria-label="Heatmap layer">
          {LAYERS.map((l) => (
            <button
              key={l.id}
              role="radio"
              aria-checked={p.layer === l.id}
              className={p.layer === l.id ? 'on' : ''}
              onClick={() => p.onLayer(l.id)}
            >
              {l.label}
            </button>
          ))}
        </div>
        <label className="toggle small">
          <input type="checkbox" checked={p.visible} onChange={(e) => p.onVisible(e.target.checked)} />
          <span className="toggle-track" aria-hidden />
          <span>Heatmap</span>
        </label>
      </div>

      <div className="fc-slider">
        <button
          className="play"
          onClick={() => onPlaying(!playing)}
          aria-label={playing ? 'Pause forecast animation' : 'Play forecast animation'}
          disabled={!heatmap}
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <input
          type="range"
          min={0}
          max={MAX_HOUR}
          step={1}
          value={hour}
          onChange={(e) => {
            onPlaying(false)
            onHour(Number(e.target.value))
          }}
          aria-label="Forecast hour after departure"
          aria-valuetext={`${formatTime(t)}, departure plus ${hour} hours`}
        />
        <span className="fc-hours" aria-hidden>
          0 h<span>24 h</span>48 h
        </span>
      </div>

      <div className="fc-bottom">
        <Legend layer={p.layer} />
        <div className="fc-readout">
          {p.heatLoading && (
            <span className="muted">
              <span className="spinner small" /> Loading corridor forecast…
            </span>
          )}
          {p.heatError && <span className="error-text">{p.heatError}</span>}
          {values && cell >= 0 && (
            <span>
              <i className="dot" style={{ background: levelColor(values.risk[hour][cell]) }} />
              {levelLabel(values.risk[hour][cell])} · {values.wind[hour][cell].toFixed(0)} mph (gust{' '}
              {values.gust[hour][cell].toFixed(0)}) · rain {values.rain[hour][cell].toFixed(2)}″ · snow{' '}
              {values.snow[hour][cell].toFixed(2)}″
            </span>
          )}
          {values && cell < 0 && p.route && (
            <span>
              <i className="dot" style={{ background: routeColor(p.route.id) }} />
              Truck {p.route.id}: {truckState}
            </span>
          )}
        </div>
      </div>
    </section>
  )
}
