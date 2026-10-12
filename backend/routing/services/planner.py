"""Orchestrates a trip plan: routes -> checkpoints & ETAs -> weather -> risk -> ranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cmp_to_key, partial

from . import geo, routing, weather
from .recommendation import HARD_RISK_CRITERIA, RouteMetrics, compare, recommend
from .risk import Assessment, RiskLevel, assess
from .timeline import Timeline, build_timeline

ROUTE_IDS = "ABC"
# Re-evaluate the same checkpoints for later departures to suggest a safer window.
DEPARTURE_SCAN_HOURS = list(range(0, 25, 2))


@dataclass
class PlanRequest:
    origin: geo.LonLat
    destination: geo.LonLat
    origin_label: str
    destination_label: str
    departure: datetime  # timezone-aware
    load_lbs: float
    interval_mi: int  # 10 / 25 / 50
    hos: bool = True


@dataclass
class Checkpoint:
    mile: float
    point: geo.LonLat
    elapsed_s: float  # seconds after departure
    owned_from: float  # this checkpoint represents miles [owned_from, owned_to)
    owned_to: float

    @property
    def owned_miles(self) -> float:
        return self.owned_to - self.owned_from


@dataclass
class PreparedRoute:
    id: str
    raw: routing.RawRoute
    cum: list[float]  # cumulative miles per coordinate (OSRM distances)
    timeline: Timeline
    checkpoints: list[Checkpoint]


def checkpoint_miles(total: float, interval: float) -> list[float]:
    """0, N, 2N, ... plus the destination. A final regular checkpoint within a
    mile of the destination is merged into it."""
    marks = [k * interval for k in range(int(total // interval) + 1)]
    if total - marks[-1] < 1.0 and len(marks) > 1:
        marks[-1] = total
    elif marks[-1] < total:
        marks.append(total)
    return marks


def build_checkpoints(coords, cum, timeline: Timeline, interval: float) -> list[Checkpoint]:
    marks = checkpoint_miles(cum[-1], interval)
    out = []
    for i, mile in enumerate(marks):
        lo = 0.0 if i == 0 else (marks[i - 1] + mile) / 2
        hi = cum[-1] if i == len(marks) - 1 else (mile + marks[i + 1]) / 2
        point, _ = geo.interpolate_along(coords, cum, mile)
        out.append(Checkpoint(mile, point, timeline.seconds_at(mile), lo, hi))
    return out


def prepare_route(route_id: str, raw: routing.RawRoute, interval: float, hos: bool) -> PreparedRoute:
    cum = [0.0]
    for seg in raw.seg_miles:
        cum.append(cum[-1] + seg)
    timeline = build_timeline(raw.seg_miles, raw.seg_seconds, hos)
    return PreparedRoute(route_id, raw, cum, timeline, build_checkpoints(raw.coords, cum, timeline, interval))


def _metrics(route_id: str, levels: list[int], checkpoints: list[Checkpoint], duration_s: float) -> RouteMetrics:
    by_level: dict[int, float] = {int(lvl): 0.0 for lvl in RiskLevel}
    weighted = 0.0
    for lvl, cp in zip(levels, checkpoints, strict=True):
        by_level[lvl] += cp.owned_miles
        weighted += lvl * cp.owned_miles
    total = sum(cp.owned_miles for cp in checkpoints) or 1.0
    return RouteMetrics(route_id, by_level, weighted / total, duration_s)


def _levels_for(route: PreparedRoute, series, departure_ts: float, load: float, offset_s: float) -> list[int]:
    levels = []
    for cp in route.checkpoints:
        wx = series[weather.snap(cp.point)].at(departure_ts + offset_s + cp.elapsed_s)
        levels.append(int(assess(wx["wind_mph"], wx["rain_in_hr"], wx["snow_in_hr"], load).level))
    return levels


@dataclass
class RouteEvaluation:
    route: PreparedRoute
    weather: list[dict]  # conditions at each checkpoint's ETA
    assessments: list[Assessment]
    metrics: RouteMetrics
    scan: list[tuple[int, RouteMetrics]]  # (departure delay h, metrics), delay 0 first

    @property
    def levels(self) -> list[int]:
        return [int(a.level) for a in self.assessments]


def evaluate_route(route: PreparedRoute, series, departure_ts: float, load: float) -> RouteEvaluation:
    wx = [series[weather.snap(cp.point)].at(departure_ts + cp.elapsed_s) for cp in route.checkpoints]
    assessments = [assess(w["wind_mph"], w["rain_in_hr"], w["snow_in_hr"], load) for w in wx]
    duration = route.timeline.total_seconds
    metrics = _metrics(route.id, [int(a.level) for a in assessments], route.checkpoints, duration)
    scan = [(0, metrics)] + [
        (h, _metrics(route.id, _levels_for(route, series, departure_ts, load, h * 3600), route.checkpoints, duration))
        for h in DEPARTURE_SCAN_HOURS
        if h > 0
    ]
    return RouteEvaluation(route, wx, assessments, metrics, scan)


# --- Serialisation helpers --------------------------------------------------


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def _risk_segments(route: PreparedRoute, levels: list[int]) -> list[dict]:
    """Mile ranges of equal risk, for colouring the route line on the map.

    The frontend slices its (simplified) path by ``path_miles`` to draw them.
    """
    segments: list[dict] = []
    for lvl, cp in zip(levels, route.checkpoints, strict=True):
        if cp.owned_miles <= 0:
            continue
        if segments and segments[-1]["level"] == lvl:
            segments[-1]["to_mile"] = cp.owned_to
        else:
            segments.append({"level": lvl, "from_mile": cp.owned_from, "to_mile": cp.owned_to})
    return [{**seg, "from_mile": round(seg["from_mile"], 3), "to_mile": round(seg["to_mile"], 3)} for seg in segments]


def _display_path(route: PreparedRoute) -> tuple[list, list[float], list[float]]:
    """Simplified geometry with per-vertex miles and elapsed seconds.

    Stop locations are inserted twice (arrive / depart) so a time-based
    animation parks the truck during a break instead of crawling.
    """
    coords, cum, timeline = route.raw.coords, route.cum, route.timeline
    tolerance = 0.0004 if cum[-1] < 300 else 0.001
    keep = geo.simplify_indices(coords, tolerance)
    pts = [(cum[i], coords[i]) for i in keep]
    path, miles, secs = [], [], []
    stops = iter(timeline.stops)
    nxt = next(stops, None)
    for mile, pt in pts:
        while nxt is not None and nxt.mile <= mile:
            sp, _ = geo.interpolate_along(coords, cum, nxt.mile)
            for t in (nxt.start_s, nxt.start_s + nxt.duration_s):
                path.append([round(sp[0], 5), round(sp[1], 5)])
                miles.append(round(nxt.mile, 3))
                secs.append(round(t))
            nxt = next(stops, None)
        path.append([round(pt[0], 5), round(pt[1], 5)])
        miles.append(round(mile, 3))
        secs.append(round(timeline.seconds_at(mile)))
    return path, miles, secs


def _route_name(route: PreparedRoute) -> str:
    return f"Route {route.id}"


def _miles_dict(m: RouteMetrics) -> dict[str, float]:
    return {lvl.key: round(m.miles(lvl), 1) for lvl in RiskLevel}


def serialize_route(ev: RouteEvaluation, departure_ts: float) -> dict:
    route, levels, metrics = ev.route, ev.levels, ev.metrics
    coords, cum = route.raw.coords, route.cum
    path, path_miles, path_s = _display_path(route)
    checkpoints = []
    for cp, a, wx in zip(route.checkpoints, ev.assessments, ev.weather, strict=True):
        checkpoints.append(
            {
                "mile": round(cp.mile, 1),
                "lon": round(cp.point[0], 5),
                "lat": round(cp.point[1], 5),
                "eta": _iso(departure_ts + cp.elapsed_s),
                "elapsed_s": round(cp.elapsed_s),
                "owned_miles": round(cp.owned_miles, 2),
                "wind_mph": round(wx["wind_mph"], 1),
                "gust_mph": round(wx["gust_mph"], 1),
                "rain_in_hr": round(wx["rain_in_hr"], 3),
                "snow_in_hr": round(wx["snow_in_hr"], 3),
                "temp_f": round(wx["temp_f"], 1),
                "weather_code": wx["weather_code"],
                "risk": a.to_dict(),
            }
        )
    stops = []
    for s in route.timeline.stops:
        p, _ = geo.interpolate_along(coords, cum, s.mile)
        stops.append(
            {
                "kind": s.kind,
                "mile": round(s.mile, 1),
                "lon": round(p[0], 5),
                "lat": round(p[1], 5),
                "start": _iso(departure_ts + s.start_s),
                "end": _iso(departure_ts + s.start_s + s.duration_s),
                "duration_s": s.duration_s,
            }
        )
    return {
        "id": route.id,
        "name": _route_name(route),
        "roads": route.raw.roads,
        "source": route.raw.source,
        "distance_mi": round(cum[-1], 1),
        "drive_s": round(route.timeline.drive_seconds),
        "trip_s": round(route.timeline.total_seconds),
        "arrival": _iso(departure_ts + route.timeline.total_seconds),
        "path": path,
        "path_miles": path_miles,
        "path_s": path_s,
        "segments": _risk_segments(route, levels),
        "checkpoints": checkpoints,
        "stops": stops,
        "metrics": {
            "miles_by_level": _miles_dict(metrics),
            "avg_risk": round(metrics.avg_risk, 3),
            "max_level": max(levels),
        },
        "departure_scan": [
            {"offset_h": h, "miles_by_level": _miles_dict(m), "avg_risk": round(m.avg_risk, 3)} for h, m in ev.scan
        ],
    }


def _departure_advice(scans: dict[str, list[tuple[int, RouteMetrics]]], chosen: RouteMetrics) -> dict | None:
    """Earliest later departure (on any route) that reaches the lowest achievable
    No Travel / Severe / High mileage, if that beats leaving now on the chosen
    route. Smaller gains (a few Moderate miles) are not worth a delay."""
    risk_cmp = partial(compare, depth=HARD_RISK_CRITERIA)
    better = [
        (offset, route_id, m) for route_id, rows in scans.items() for offset, m in rows if risk_cmp(m, chosen) < 0
    ]
    if not better:
        return None
    lowest = min((m for _, _, m in better), key=cmp_to_key(risk_cmp))
    offset, route_id, m = min((c for c in better if risk_cmp(c[2], lowest) == 0), key=lambda c: (c[0], c[2].duration_s))
    return {
        "offset_h": offset,
        "route_id": route_id,
        "miles_by_level": _miles_dict(m),
        "avg_risk": round(m.avg_risk, 3),
        "baseline": {
            "route_id": chosen.route_id,
            "miles_by_level": _miles_dict(chosen),
            "avg_risk": round(chosen.avg_risk, 3),
        },
    }


def build_plan(req: PlanRequest) -> dict:
    raw_routes = routing.get_route_options(req.origin, req.destination)
    routes = [prepare_route(ROUTE_IDS[i], raw, req.interval_mi, req.hos) for i, raw in enumerate(raw_routes[:3])]
    departure_ts = req.departure.timestamp()

    # One weather fetch covering every checkpoint, from departure through the
    # latest arrival plus the departure-scan horizon.
    points = [weather.snap(cp.point) for r in routes for cp in r.checkpoints]
    horizon = max(r.timeline.total_seconds for r in routes) + max(DEPARTURE_SCAN_HOURS) * 3600
    series = weather.fetch_hourly(points, departure_ts, departure_ts + horizon)

    evals = [evaluate_route(r, series, departure_ts, req.load_lbs) for r in routes]
    names = {r.id: _route_name(r) for r in routes}
    rec = recommend([ev.metrics for ev in evals], names)
    chosen = next(ev.metrics for ev in evals if ev.route.id == rec["route_id"])
    later = {ev.route.id: [row for row in ev.scan if row[0] > 0] for ev in evals}

    return {
        "inputs": {
            "origin": {"label": req.origin_label, "lon": req.origin[0], "lat": req.origin[1]},
            "destination": {"label": req.destination_label, "lon": req.destination[0], "lat": req.destination[1]},
            "departure": _iso(departure_ts),
            "load_lbs": req.load_lbs,
            "interval_mi": req.interval_mi,
            "hos": req.hos,
        },
        "routes": [serialize_route(ev, departure_ts) for ev in evals],
        "recommendation": rec,
        "departure_advice": _departure_advice(later, chosen),
    }
