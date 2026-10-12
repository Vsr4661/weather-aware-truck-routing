import { memo } from 'react'
import { formatDuration, formatMiles, formatTime } from '../lib/format'
import { LEVELS, levelColor, levelLabel, routeColor, totalMiles } from '../lib/risk'
import type { MilesByLevel, Plan, Route } from '../types'

export function RiskBar({ miles, height = 8 }: { miles: MilesByLevel; height?: number }) {
  const total = totalMiles(miles) || 1
  const title = LEVELS.filter((l) => miles[l.key] > 0)
    .map((l) => `${l.label}: ${Math.round(miles[l.key])} mi`)
    .join(' · ')
  return (
    <div className="risk-bar" style={{ height }} title={title} role="img" aria-label={title}>
      {LEVELS.map((l) =>
        miles[l.key] > 0 ? (
          <span key={l.key} style={{ width: `${(miles[l.key] / total) * 100}%`, background: l.color }} />
        ) : null,
      )}
    </div>
  )
}

function MilesSummary({ miles }: { miles: MilesByLevel }) {
  const notable = LEVELS.filter((l) => l.level >= 2 && miles[l.key] >= 0.5)
  if (!notable.length) return <span className="ok">No High or Severe miles</span>
  return (
    <span className="miles-summary">
      {notable.map((l) => (
        <span key={l.key} style={{ color: l.color }}>
          {Math.round(miles[l.key])} mi {l.label}
        </span>
      ))}
    </span>
  )
}

export const RecommendationCard = memo(function RecommendationCard({ plan, onSelect }: { plan: Plan; onSelect: (id: string) => void }) {
  const rec = plan.recommendation
  const route = plan.routes.find((r) => r.id === rec.route_id)!
  const advice = plan.departure_advice
  const departure = new Date(plan.inputs.departure).getTime()
  return (
    <section className={`rec-card${rec.unsafe ? ' unsafe' : ''}`} aria-live="polite">
      <div className="rec-eyebrow">{rec.unsafe ? '⚠ No safe route at this departure time' : 'Recommended'}</div>
      <button className="rec-title" onClick={() => onSelect(route.id)}>
        <span className="route-badge" style={{ background: routeColor(route.id) }}>
          {route.id}
        </span>
        {route.name}
        {route.roads.length > 0 && <span className="muted"> via {route.roads.slice(0, 2).join(', ')}</span>}
      </button>
      <p className="rec-reason">{rec.reason}</p>
      {rec.unsafe && (
        <p className="rec-warn">
          Every option crosses No Travel conditions. The least-bad route is shown; delaying departure is strongly
          advised.
        </p>
      )}
      {advice && (
        <div className="advice">
          <b>Safer window:</b> leaving <b>{advice.offset_h} h later</b> (
          {formatTime(new Date(departure + advice.offset_h * 3600_000))}) on Route {advice.route_id}:{' '}
          <MilesSummary miles={advice.miles_by_level} />
          <span className="muted"> instead of </span>
          <MilesSummary miles={advice.baseline.miles_by_level} />.
        </div>
      )}
    </section>
  )
})

export const RouteCards = memo(function RouteCards({
  plan,
  selectedId,
  onSelect,
}: {
  plan: Plan
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const rank = plan.recommendation.ranking
  return (
    <div className="route-cards" role="radiogroup" aria-label="Route options">
      {plan.routes.map((r) => {
        const isRec = r.id === plan.recommendation.route_id
        return (
          <button
            key={r.id}
            role="radio"
            aria-checked={r.id === selectedId}
            className={`route-card${r.id === selectedId ? ' selected' : ''}`}
            style={{ '--c': routeColor(r.id) } as React.CSSProperties}
            onClick={() => onSelect(r.id)}
          >
            <div className="rc-head">
              <span className="route-badge" style={{ background: routeColor(r.id) }}>
                {r.id}
              </span>
              <span className="rc-roads">{r.roads.slice(0, 2).join(' · ') || r.name}</span>
              <span className={`rank${isRec ? ' best' : ''}`}>{isRec ? '★ Best' : `#${rank.indexOf(r.id) + 1}`}</span>
            </div>
            <div className="rc-stats">
              <div>
                <b>{formatMiles(r.distance_mi)}</b>
                <small>distance</small>
              </div>
              <div>
                <b>{formatDuration(r.drive_s)}</b>
                <small>driving</small>
              </div>
              <div>
                <b>{formatDuration(r.trip_s)}</b>
                <small>{r.stops.length ? `trip · ${r.stops.length} stop${r.stops.length > 1 ? 's' : ''}` : 'trip'}</small>
              </div>
              <div>
                <b>{formatTime(r.arrival)}</b>
                <small>arrive</small>
              </div>
            </div>
            <RiskBar miles={r.metrics.miles_by_level} />
            <div className="rc-foot">
              <MilesSummary miles={r.metrics.miles_by_level} />
              <span className="muted">
                avg risk {r.metrics.avg_risk.toFixed(2)} · worst{' '}
                <span style={{ color: levelColor(r.metrics.max_level) }}>{levelLabel(r.metrics.max_level)}</span>
              </span>
            </div>
            {!isRec && plan.recommendation.comparisons[r.id] && (
              <div className="rc-why">{plan.recommendation.comparisons[r.id]}</div>
            )}
          </button>
        )
      })}
    </div>
  )
})

/** Risk mileage if leaving 0-24 h later, from the same checkpoint forecasts. */
function DepartureStrip({ route }: { route: Route }) {
  const max = Math.max(...route.departure_scan.map((s) => totalMiles(s.miles_by_level)))
  return (
    <div className="scan">
      <div className="scan-title">
        If you leave later <span className="muted">(risk mix by departure delay)</span>
      </div>
      <div className="scan-bars">
        {route.departure_scan.map((s) => (
          <div key={s.offset_h} className="scan-col" title={`+${s.offset_h} h · avg risk ${s.avg_risk.toFixed(2)}`}>
            <div className="scan-stack" style={{ height: `${(totalMiles(s.miles_by_level) / max) * 100}%` }}>
              {[...LEVELS].reverse().map((l) =>
                s.miles_by_level[l.key] > 0 ? (
                  <span
                    key={l.key}
                    style={{ flexGrow: s.miles_by_level[l.key], background: l.color, opacity: l.level === 0 ? 0.35 : 1 }}
                  />
                ) : null,
              )}
            </div>
            <small>{s.offset_h === 0 ? 'now' : `+${s.offset_h}`}</small>
          </div>
        ))}
      </div>
    </div>
  )
}

export const RouteDetail = memo(function RouteDetail({
  route,
  onFocusCheckpoint,
}: {
  route: Route
  onFocusCheckpoint: (index: number) => void
}) {
  // Interleave HOS stops with checkpoints by mile.
  type Row = { kind: 'cp'; index: number; mile: number } | { kind: 'stop'; index: number; mile: number }
  const rows: Row[] = [
    ...route.checkpoints.map((c, index) => ({ kind: 'cp' as const, index, mile: c.mile })),
    ...route.stops.map((s, index) => ({ kind: 'stop' as const, index, mile: s.mile })),
  ].sort((a, b) => a.mile - b.mile || (a.kind === 'cp' ? -1 : 1))

  return (
    <section className="detail">
      <h3>
        <span className="route-badge" style={{ background: routeColor(route.id) }}>
          {route.id}
        </span>
        Checkpoints <span className="muted">· {route.checkpoints.length} samples at ETA</span>
      </h3>
      <DepartureStrip route={route} />
      <ol className="cp-list">
        {rows.map((row) => {
          if (row.kind === 'stop') {
            const s = route.stops[row.index]
            return (
              <li key={`s${row.index}`} className="cp-stop">
                <span className={`stop-ico stop-${s.kind}`}>{s.kind === 'rest' ? 'Z' : 'P'}</span>
                <span>
                  {s.kind === 'rest' ? '10-h rest (HOS)' : '30-min break (HOS)'} · mile {s.mile.toFixed(0)}
                </span>
                <span className="muted">
                  {formatTime(s.start)} – {formatTime(s.end)}
                </span>
              </li>
            )
          }
          const cp = route.checkpoints[row.index]
          return (
            <li key={`c${row.index}`}>
              <button className="cp-row" onClick={() => onFocusCheckpoint(row.index)}>
                <span className="cp-dot" style={{ background: levelColor(cp.risk.level) }} />
                <span className="cp-mile">{cp.mile.toFixed(0)} mi</span>
                <span className="cp-eta">{formatTime(cp.eta)}</span>
                <span className="cp-wx">
                  <span title="Sustained wind (gust)">
                    {cp.wind_mph.toFixed(0)}
                    <small>/{cp.gust_mph.toFixed(0)} mph</small>
                  </span>
                  <span title="Rain in/hr" className={cp.rain_in_hr >= 0.1 ? 'hot' : ''}>
                    {cp.rain_in_hr.toFixed(2)}″ rain
                  </span>
                  {cp.snow_in_hr > 0 && (
                    <span title="Snow in/hr" className={cp.snow_in_hr >= 0.5 ? 'hot' : ''}>
                      {cp.snow_in_hr.toFixed(2)}″ snow
                    </span>
                  )}
                </span>
                <span className="cp-level" style={{ color: levelColor(cp.risk.level) }}>
                  {cp.risk.label}
                  {cp.risk.load_rule && <span title={cp.risk.load_rule}> ⚖</span>}
                </span>
              </button>
            </li>
          )
        })}
      </ol>
    </section>
  )
})
