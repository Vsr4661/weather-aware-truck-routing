import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, fetchHeatmap, planTrip } from './api'
import ForecastPanel from './components/ForecastPanel'
import MapView, { type MapFocus } from './components/MapView'
import { RecommendationCard, RouteCards, RouteDetail } from './components/Results'
import TripForm from './components/TripForm'
import { HeatmapFrames } from './lib/heatmapRaster'
import { LEVELS } from './lib/risk'
import type { HeatLayer, Heatmap, Plan, PlanInput } from './types'

function usePrefersDark(): boolean {
  const query = '(prefers-color-scheme: dark)'
  const [dark, setDark] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return dark
}

export default function App() {
  const dark = usePrefersDark()
  const [plan, setPlan] = useState<Plan | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [focus, setFocus] = useState<MapFocus | null>(null)

  const [heatmap, setHeatmap] = useState<Heatmap | null>(null)
  const [heatLoading, setHeatLoading] = useState(false)
  const [heatError, setHeatError] = useState<string | null>(null)
  const [heatLayer, setHeatLayer] = useState<HeatLayer>('risk')
  const [heatVisible, setHeatVisible] = useState(true)
  const [hour, setHour] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [hoverCell, setHoverCell] = useState(-1)
  const planCtrl = useRef<AbortController | null>(null)

  const submit = useCallback(async (input: PlanInput) => {
    planCtrl.current?.abort()
    const ctrl = new AbortController()
    planCtrl.current = ctrl
    setLoading(true)
    setError(null)
    setPlaying(false)
    try {
      const result = await planTrip(input, ctrl.signal)
      setPlan(result)
      setSelectedId(result.recommendation.route_id)
      setHour(0)
      setFocus(null)
      if (window.innerWidth < 900) {
        requestAnimationFrame(() => document.querySelector('.results')?.scrollIntoView({ behavior: 'smooth' }))
      }
    } catch (e) {
      if (!ctrl.signal.aborted) setError(e instanceof ApiError ? e.message : 'Something went wrong.')
    } finally {
      if (!ctrl.signal.aborted) setLoading(false)
    }
  }, [])

  // The heatmap loads after the plan so routes appear as soon as possible.
  useEffect(() => {
    setHeatmap(null)
    setHeatError(null)
    if (!plan) return
    const ctrl = new AbortController()
    setHeatLoading(true)
    fetchHeatmap(plan, ctrl.signal)
      .then(setHeatmap)
      .catch((e) => !ctrl.signal.aborted && setHeatError(e instanceof ApiError ? e.message : 'Heatmap unavailable'))
      .finally(() => !ctrl.signal.aborted && setHeatLoading(false))
    return () => ctrl.abort()
  }, [plan])

  const frames = useMemo(() => (heatmap ? new HeatmapFrames(heatmap) : null), [heatmap])

  useEffect(() => {
    if (!frames) return
    let cancelled = false
    frames.warm(heatLayer, () => cancelled)
    return () => {
      cancelled = true
    }
  }, [frames, heatLayer])

  const departureTs = plan ? new Date(plan.inputs.departure).getTime() / 1000 : 0
  const baseTime = heatmap?.times[0] ?? Math.floor(departureTs / 3600) * 3600
  const elapsed = baseTime + hour * 3600 - departureTs
  const selected = plan?.routes.find((r) => r.id === selectedId) ?? null

  const focusCheckpoint = useCallback(
    (index: number) => selectedId && setFocus({ routeId: selectedId, index, nonce: Date.now() }),
    [selectedId],
  )

  return (
    <div className="app">
      <aside className="panel">
        <header className="brand">
          <svg viewBox="0 0 32 32" className="logo" aria-hidden>
            <rect width="32" height="32" rx="8" />
            <path d="M7 22c4-9 8-12 18-13" />
            <circle cx="7" cy="22" r="3" className="o" />
            <circle cx="25" cy="9" r="3" className="d" />
          </svg>
          <div>
            <h1>RouteCast</h1>
            <p>Weather-aware truck routing</p>
          </div>
        </header>

        <TripForm loading={loading} onSubmit={submit} />

        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}

        {plan && (
          <div className="results">
            <RecommendationCard plan={plan} onSelect={setSelectedId} />
            <RouteCards plan={plan} selectedId={selectedId} onSelect={setSelectedId} />
            {selected && <RouteDetail route={selected} onFocusCheckpoint={focusCheckpoint} />}
          </div>
        )}

        {!plan && !loading && (
          <section className="howto">
            <h2>How it works</h2>
            <ol>
              <li>Up to 3 route options come from OSRM, with ETAs adjusted for a truck (65 mph cap, optional HOS breaks).</li>
              <li>Weather is sampled every 10 / 25 / 50 miles at the hour the truck actually gets there.</li>
              <li>Each checkpoint is rated with the wind / rain / snow thresholds and load rules.</li>
              <li>Routes are ranked by Severe miles, then High miles, average risk and travel time.</li>
            </ol>
            <div className="legend">
              {LEVELS.map((l) => (
                <span key={l.key}>
                  <i style={{ background: l.color }} />
                  {l.label}
                </span>
              ))}
            </div>
          </section>
        )}

        <footer className="credits">
          Routing © OSRM / OpenStreetMap · Weather © Open-Meteo, MET Norway · Geocoding © Photon
        </footer>
      </aside>

      <main className="map-wrap">
        <MapView
          plan={plan}
          selectedId={selectedId}
          onSelectRoute={setSelectedId}
          frames={frames}
          heatLayer={heatLayer}
          heatVisible={heatVisible}
          hour={hour}
          elapsed={elapsed}
          focus={focus}
          onHoverCell={setHoverCell}
          dark={dark}
        />
        {plan && (
          <ForecastPanel
            heatmap={heatmap}
            heatLoading={heatLoading}
            heatError={heatError}
            layer={heatLayer}
            onLayer={setHeatLayer}
            visible={heatVisible}
            onVisible={setHeatVisible}
            hour={hour}
            onHour={setHour}
            playing={playing}
            onPlaying={setPlaying}
            baseTime={baseTime}
            departureTs={departureTs}
            hoverCell={hoverCell}
            route={selected}
          />
        )}
        {loading && (
          <div className="map-loading" role="status">
            <span className="spinner" /> Routing and sampling forecasts at each checkpoint ETA…
          </div>
        )}
      </main>
    </div>
  )
}
