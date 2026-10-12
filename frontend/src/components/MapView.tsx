import maplibregl, { type GeoJSONSource, type ImageSource, type MapLayerMouseEvent } from 'maplibre-gl'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { HeatmapFrames } from '../lib/heatmapRaster'
import { formatDuration, formatMiles, formatTime } from '../lib/format'
import { levelColor, levelLabel, routeColor, weatherText } from '../lib/risk'
import { positionAt, slicePath } from '../lib/route'
import type { Checkpoint, HeatLayer, Plan, Route } from '../types'

const STYLES = {
  light: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
  dark: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
}

export interface MapFocus {
  routeId: string
  index: number // checkpoint index
  nonce: number
}

interface Props {
  plan: Plan | null
  selectedId: string | null
  onSelectRoute: (id: string) => void
  frames: HeatmapFrames | null
  heatLayer: HeatLayer
  heatVisible: boolean
  hour: number
  elapsed: number // seconds after departure at the slider time
  focus: MapFocus | null
  onHoverCell: (cell: number) => void
  dark: boolean
}

type FC = GeoJSON.FeatureCollection

const empty = (): FC => ({ type: 'FeatureCollection', features: [] })

function checkpointPopup(route: Route, cp: Checkpoint): string {
  const r = cp.risk
  const drivers = r.drivers.length ? ` · driven by ${r.drivers.join(' + ')}` : ''
  const rule = r.load_rule ? `<div class="pop-rule">⚖ ${r.load_rule}</div>` : ''
  return `
    <div class="pop">
      <div class="pop-head">
        <span class="chip" style="--c:${levelColor(r.level)}">${r.label}</span>
        <span>${route.name} · mile ${cp.mile.toFixed(0)}</span>
      </div>
      <div class="pop-eta">ETA <b>${formatTime(cp.eta)}</b> · ${weatherText(cp.weather_code)}${drivers}</div>
      <table class="pop-grid">
        <tr><td>Wind</td><td>${cp.wind_mph.toFixed(0)} mph <span class="muted">(gust ${cp.gust_mph.toFixed(0)})</span></td><td><i style="--c:${levelColor(r.wind_level)}"></i>${levelLabel(r.wind_level)}</td></tr>
        <tr><td>Rain</td><td>${cp.rain_in_hr.toFixed(2)} in/hr</td><td><i style="--c:${levelColor(r.rain_level)}"></i>${levelLabel(r.rain_level)}</td></tr>
        <tr><td>Snow</td><td>${cp.snow_in_hr.toFixed(2)} in/hr</td><td><i style="--c:${levelColor(r.snow_level)}"></i>${levelLabel(r.snow_level)}</td></tr>
        <tr><td>Temp</td><td>${cp.temp_f.toFixed(0)}°F</td><td></td></tr>
      </table>
      ${rule}
    </div>`
}

function markerEl(className: string, html = ''): HTMLDivElement {
  const el = document.createElement('div')
  el.className = className
  el.innerHTML = html
  return el
}

export default function MapView(props: Props) {
  const { plan, selectedId, frames, heatLayer, heatVisible, hour, elapsed, focus, dark } = props
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const [styleVersion, setStyleVersion] = useState(0)
  const hoverPopup = useRef<maplibregl.Popup | null>(null)
  const pinnedPopup = useRef<maplibregl.Popup | null>(null)
  const markers = useRef<maplibregl.Marker[]>([])
  const trucks = useRef<Map<string, maplibregl.Marker>>(new Map())
  // Event handlers read the latest props through a ref (registered once).
  const live = useRef(props)
  live.current = props

  // --- map lifecycle ------------------------------------------------------
  useEffect(() => {
    const map = new maplibregl.Map({
      container: container.current!,
      style: dark ? STYLES.dark : STYLES.light,
      center: [-96, 38.5],
      zoom: 3.6,
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    })
    map.touchZoomRotate.disableRotation()
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new maplibregl.ScaleControl({ unit: 'imperial' }), 'bottom-right')
    map.on('style.load', () => setStyleVersion((v) => v + 1))
    mapRef.current = map
    hoverPopup.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '300px', offset: 10 })
    pinnedPopup.current = new maplibregl.Popup({ closeButton: true, maxWidth: '300px', offset: 10 })

    const onCheckpointHover = (e: MapLayerMouseEvent) => {
      const f = e.features?.[0]
      const p = live.current.plan
      if (!f || !p) return
      map.getCanvas().style.cursor = 'pointer'
      const route = p.routes.find((r) => r.id === f.properties.route)
      const cp = route?.checkpoints[f.properties.idx as number]
      if (route && cp) hoverPopup.current!.setLngLat([cp.lon, cp.lat]).setHTML(checkpointPopup(route, cp)).addTo(map)
    }
    map.on('mousemove', 'checkpoints', onCheckpointHover)
    map.on('mouseleave', 'checkpoints', () => {
      map.getCanvas().style.cursor = ''
      hoverPopup.current!.remove()
    })
    map.on('click', 'checkpoints', (e) => {
      const f = e.features?.[0]
      if (f) live.current.onSelectRoute(f.properties.route as string)
    })
    map.on('mouseenter', 'routes-hit', () => (map.getCanvas().style.cursor = 'pointer'))
    map.on('mouseleave', 'routes-hit', () => (map.getCanvas().style.cursor = ''))
    map.on('click', 'routes-hit', (e) => {
      if (map.queryRenderedFeatures(e.point, { layers: ['checkpoints'] }).length) return
      const f = e.features?.[0]
      if (f) live.current.onSelectRoute(f.properties.id as string)
    })
    map.on('mousemove', (e) => {
      const fr = live.current.frames
      live.current.onHoverCell(fr && live.current.heatVisible ? fr.cellAt(e.lngLat.lng, e.lngLat.lat) : -1)
    })
    map.getCanvas().addEventListener('mouseleave', () => live.current.onHoverCell(-1))

    return () => map.remove()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Theme switch: swapping the style drops our layers; style.load re-adds them.
  const firstTheme = useRef(true)
  useEffect(() => {
    if (firstTheme.current) {
      firstTheme.current = false
      return
    }
    mapRef.current?.setStyle(dark ? STYLES.dark : STYLES.light)
  }, [dark])

  // --- layers (re-created after every style load) -------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || !styleVersion || map.getLayer('routes-hit')) return
    const isDark = live.current.dark
    for (const id of ['routes', 'segments', 'checkpoints']) {
      if (!map.getSource(id)) map.addSource(id, { type: 'geojson', data: empty() })
    }
    // Wide invisible line for easy clicking.
    map.addLayer({ id: 'routes-hit', type: 'line', source: 'routes', paint: { 'line-width': 18, 'line-opacity': 0 } })
    map.addLayer({
      id: 'routes-casing',
      type: 'line',
      source: 'routes',
      layout: { 'line-cap': 'round', 'line-join': 'round', 'line-sort-key': ['get', 'order'] },
      paint: {
        'line-color': isDark ? '#0b1220' : '#ffffff',
        'line-width': ['case', ['get', 'selected'], 11, 7],
        'line-opacity': 0.9,
      },
    })
    map.addLayer({
      id: 'routes-line',
      type: 'line',
      source: 'routes',
      layout: { 'line-cap': 'round', 'line-join': 'round', 'line-sort-key': ['get', 'order'] },
      paint: {
        'line-color': ['get', 'color'],
        'line-width': ['case', ['get', 'selected'], 8, 4],
        'line-opacity': ['case', ['get', 'selected'], 1, 0.6],
      },
    })
    map.addLayer({
      id: 'segments-line',
      type: 'line',
      source: 'segments',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': ['get', 'color'], 'line-width': 3.5 },
    })
    map.addLayer({
      id: 'checkpoints',
      type: 'circle',
      source: 'checkpoints',
      layout: { 'circle-sort-key': ['get', 'order'] },
      paint: {
        'circle-color': ['get', 'color'],
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, ['case', ['get', 'selected'], 4, 2.5], 9, ['case', ['get', 'selected'], 7.5, 4.5]],
        'circle-stroke-color': isDark ? '#0b1220' : '#ffffff',
        'circle-stroke-width': ['case', ['get', 'selected'], 1.8, 1],
        'circle-opacity': ['case', ['get', 'selected'], 1, 0.75],
        'circle-stroke-opacity': ['case', ['get', 'selected'], 1, 0.75],
      },
    })
  }, [styleVersion])

  // --- route data ---------------------------------------------------------
  const routeFC = useMemo<FC>(() => {
    if (!plan) return empty()
    return {
      type: 'FeatureCollection',
      features: plan.routes.map((r) => ({
        type: 'Feature',
        properties: { id: r.id, color: routeColor(r.id), selected: r.id === selectedId, order: r.id === selectedId ? 10 : 0 },
        geometry: { type: 'LineString', coordinates: r.path },
      })),
    }
  }, [plan, selectedId])

  const segmentFC = useMemo<FC>(() => {
    const route = plan?.routes.find((r) => r.id === selectedId)
    if (!route) return empty()
    return {
      type: 'FeatureCollection',
      features: route.segments.map((s) => ({
        type: 'Feature',
        properties: { level: s.level, color: levelColor(s.level) },
        geometry: { type: 'LineString', coordinates: slicePath(route, s.from_mile, s.to_mile) },
      })),
    }
  }, [plan, selectedId])

  const checkpointFC = useMemo<FC>(() => {
    if (!plan) return empty()
    return {
      type: 'FeatureCollection',
      features: plan.routes.flatMap((r) =>
        r.checkpoints.map((cp, idx) => ({
          type: 'Feature' as const,
          properties: {
            route: r.id,
            idx,
            color: levelColor(cp.risk.level),
            selected: r.id === selectedId,
            order: (r.id === selectedId ? 10 : 0) + cp.risk.level,
          },
          geometry: { type: 'Point' as const, coordinates: [cp.lon, cp.lat] },
        })),
      ),
    }
  }, [plan, selectedId])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !styleVersion) return
    ;(map.getSource('routes') as GeoJSONSource).setData(routeFC)
    ;(map.getSource('segments') as GeoJSONSource).setData(segmentFC)
    ;(map.getSource('checkpoints') as GeoJSONSource).setData(checkpointFC)
  }, [routeFC, segmentFC, checkpointFC, styleVersion])

  // Fit to the trip whenever a new plan arrives.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !plan) return
    pinnedPopup.current?.remove()
    const bounds = new maplibregl.LngLatBounds()
    plan.routes.forEach((r) => r.path.forEach((p) => bounds.extend(p)))
    const mobile = window.innerWidth < 900
    map.fitBounds(bounds, {
      padding: mobile ? { top: 40, bottom: 40, left: 30, right: 30 } : { top: 70, bottom: 190, left: 70, right: 70 },
      duration: 900,
    })
  }, [plan])

  // --- HTML markers: endpoints, route labels, HOS stops -------------------
  useEffect(() => {
    const map = mapRef.current
    markers.current.forEach((m) => m.remove())
    markers.current = []
    if (!map || !plan) return
    const { origin, destination } = plan.inputs
    const add = (m: maplibregl.Marker) => markers.current.push(m.addTo(map))
    add(new maplibregl.Marker({ element: markerEl('pin pin-origin', '<span>A</span>') }).setLngLat([origin.lon, origin.lat]))
    add(new maplibregl.Marker({ element: markerEl('pin pin-dest', '<span>B</span>') }).setLngLat([destination.lon, destination.lat]))

    for (const r of plan.routes) {
      const mid = positionAt(r, r.trip_s * (r.id === 'A' ? 0.5 : r.id === 'B' ? 0.42 : 0.58)).point
      const rec = plan.recommendation.route_id === r.id
      const el = markerEl(
        `route-label${r.id === selectedId ? ' is-selected' : ''}`,
        `<b style="--c:${routeColor(r.id)}">${r.id}</b>${formatMiles(r.distance_mi)} · ${formatDuration(r.trip_s)}${rec ? ' <span class="star">★</span>' : ''}`,
      )
      el.addEventListener('click', () => live.current.onSelectRoute(r.id))
      add(new maplibregl.Marker({ element: el, anchor: 'bottom', offset: [0, -8] }).setLngLat(mid))
    }

    const selected = plan.routes.find((r) => r.id === selectedId)
    for (const s of selected?.stops ?? []) {
      const el = markerEl(`stop stop-${s.kind}`, s.kind === 'rest' ? 'Z' : 'P')
      el.title = `${s.kind === 'rest' ? '10-h rest' : '30-min break'} · mile ${s.mile.toFixed(0)} · ${formatTime(s.start)} → ${formatTime(s.end)}`
      add(new maplibregl.Marker({ element: el }).setLngLat([s.lon, s.lat]))
    }
  }, [plan, selectedId])

  // --- trucks at the slider time ------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    trucks.current.forEach((m) => m.remove())
    trucks.current = new Map()
    if (!map || !plan) return
    for (const r of plan.routes) {
      const el = markerEl('truck', '<svg viewBox="0 0 24 24"><path d="M3 6h11v9H3zM14 9h4l3 3v3h-7z" /><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/></svg>')
      el.style.setProperty('--c', routeColor(r.id))
      trucks.current.set(r.id, new maplibregl.Marker({ element: el }).setLngLat(r.path[0]).addTo(map))
    }
  }, [plan])

  useEffect(() => {
    if (!plan) return
    for (const r of plan.routes) {
      const marker = trucks.current.get(r.id)
      if (!marker) continue
      marker.setLngLat(positionAt(r, elapsed).point)
      const el = marker.getElement()
      el.classList.toggle('is-selected', r.id === selectedId)
      el.classList.toggle('is-waiting', elapsed < 0)
      el.classList.toggle('is-done', elapsed > r.trip_s)
    }
  }, [plan, elapsed, selectedId])

  // --- heatmap image ------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || !styleVersion) return
    const src = map.getSource('heat') as ImageSource | undefined
    if (!frames) {
      if (map.getLayer('heat-layer')) map.removeLayer('heat-layer')
      if (src) map.removeSource('heat')
      return
    }
    const url = frames.frame(heatLayer, hour)
    if (!src) {
      map.addSource('heat', { type: 'image', url, coordinates: frames.coordinates })
      // Under the basemap's labels so city names stay readable.
      const below = map.getStyle().layers?.find((l) => l.type === 'symbol')?.id
      map.addLayer(
        {
          id: 'heat-layer',
          type: 'raster',
          source: 'heat',
          paint: { 'raster-fade-duration': 0, 'raster-resampling': 'linear', 'raster-opacity': 0.85 },
        },
        below,
      )
    } else {
      src.updateImage({ url, coordinates: frames.coordinates })
    }
    map.setLayoutProperty('heat-layer', 'visibility', heatVisible ? 'visible' : 'none')
  }, [frames, heatLayer, hour, heatVisible, styleVersion])

  // --- fly to a checkpoint picked in the sidebar --------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || !plan || !focus) return
    const route = plan.routes.find((r) => r.id === focus.routeId)
    const cp = route?.checkpoints[focus.index]
    if (!route || !cp) return
    map.flyTo({ center: [cp.lon, cp.lat], zoom: Math.max(map.getZoom(), 8), duration: 700 })
    pinnedPopup.current!.setLngLat([cp.lon, cp.lat]).setHTML(checkpointPopup(route, cp)).addTo(map)
  }, [focus, plan])

  return <div ref={container} className="map" role="region" aria-label="Route map" />
}
