"""Route options from OSRM.

OSRM's ``alternatives`` flag returns *up to* N routes, and often only 1-2 for
long trips. The spec requires 3 options, so when OSRM comes up short we force
extra candidates through via-points offset perpendicular to the trip, then keep
only candidates that are genuinely different (low overlap with routes we
already have) and not absurd detours.
"""

from __future__ import annotations

import hashlib
import logging
import math
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from . import geo
from .http import UpstreamError, get_json

log = logging.getLogger(__name__)

TARGET_ROUTES = 3
MAX_DETOUR_RATIO = 1.6  # reject candidates much longer/slower than the fastest route
MAX_OVERLAP = 0.80  # reject candidates sharing more than 80% of their length
MAX_BACKTRACK = 0.04  # reject candidates that double back on >4% of their length
CLEAN_BACKTRACK = 0.005  # below this a candidate counts as loop-free
OVERLAP_SAMPLE_MI = 2.0
OVERLAP_NEAR_MI = 0.6
CACHE_TTL = 60 * 60


@dataclass
class RawRoute:
    coords: list[geo.LonLat]
    seg_miles: list[float]  # len(coords) - 1
    seg_seconds: list[float]  # len(coords) - 1, OSRM (car) durations
    distance_mi: float
    duration_s: float
    roads: list[str]  # main roads by distance, e.g. ["I 80", "I 76"]
    source: str  # "osrm" | "via"


def _main_roads(legs: list[dict], top: int = 3) -> list[str]:
    by_distance: Counter[str] = Counter()
    for leg in legs:
        for step in leg.get("steps", []):
            name = (step.get("ref") or step.get("name") or "").split(";")[0].strip()
            if name:
                by_distance[name] += step.get("distance", 0)
    return [name for name, _ in by_distance.most_common(top)]


def _parse_route(route: dict, source: str) -> RawRoute:
    coords = [tuple(c) for c in route["geometry"]["coordinates"]]
    seg_m: list[float] = []
    seg_s: list[float] = []
    for leg in route["legs"]:
        ann = leg.get("annotation", {})
        seg_m.extend(ann.get("distance", []))
        seg_s.extend(ann.get("duration", []))
    if len(seg_m) != len(coords) - 1 or len(seg_s) != len(coords) - 1:
        # Defensive fallback: spread total duration proportionally to distance.
        seg_mi = [geo.haversine_mi(coords[i], coords[i + 1]) for i in range(len(coords) - 1)]
        total = sum(seg_mi) or 1.0
        seg_s = [route["duration"] * d / total for d in seg_mi]
    else:
        seg_mi = [m / geo.METERS_PER_MILE for m in seg_m]
    return RawRoute(
        coords=coords,
        seg_miles=seg_mi,
        seg_seconds=seg_s,
        distance_mi=route["distance"] / geo.METERS_PER_MILE,
        duration_s=route["duration"],
        roads=_main_roads(route["legs"]),
        source=source,
    )


def _osrm(points: list[geo.LonLat], alternatives: int = 0) -> list[dict]:
    path = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in points)
    params = {
        "overview": "full",
        "geometries": "geojson",
        "annotations": "distance,duration",
        "steps": "true",
    }
    if alternatives:
        params["alternatives"] = str(alternatives)
    data = get_json("OSRM", f"{settings.OSRM_BASE_URL}/route/v1/driving/{path}", params, timeout=25)
    if data.get("code") != "Ok":
        if data.get("code") == "NoRoute":
            return []
        raise UpstreamError("OSRM", data.get("message") or data.get("code", "routing failed"), 422)
    return data.get("routes", [])


def _overlap_ratio(candidate: RawRoute, existing: list[geo.PointIndex]) -> float:
    cum = geo.cumulative_miles(candidate.coords)
    samples = geo.resample(candidate.coords, cum, OVERLAP_SAMPLE_MI)
    worst = 0.0
    for index in existing:
        near = sum(1 for p in samples if index.any_within(p, OVERLAP_NEAR_MI))
        worst = max(worst, near / len(samples))
    return worst


def _backtrack_ratio(route: RawRoute) -> float:
    """Share of the route that doubles back over itself.

    A via-point that snaps onto a side road makes OSRM drive in and back out;
    such a route is not a real alternative.
    """
    cum = geo.cumulative_miles(route.coords)
    samples = geo.resample(route.coords, cum, 1.0)
    cell = 0.02
    buckets: dict[tuple[int, int], list[int]] = {}
    for i, (lon, lat) in enumerate(samples):
        buckets.setdefault((math.floor(lon / cell), math.floor(lat / cell)), []).append(i)
    doubled = 0
    for i, p in enumerate(samples):
        kx, ky = math.floor(p[0] / cell), math.floor(p[1] / cell)
        if any(
            abs(i - j) >= 5 and geo.haversine_mi(p, samples[j]) < 0.25
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for j in buckets.get((kx + dx, ky + dy), ())
        ):
            doubled += 1
    return doubled / len(samples)


def _loop_ratio(route: RawRoute, window_mi: int = 20, min_progress: float = 0.3) -> float:
    """Share of the route where 20 driven miles cover less than 6 straight-line miles.

    Catches small loops on parallel roads that ``_backtrack_ratio`` misses;
    real highway routes (mountain passes included) never trip it.
    """
    cum = geo.cumulative_miles(route.coords)
    samples = geo.resample(route.coords, cum, 1.0)
    if len(samples) <= window_mi:
        return 0.0
    loops = sum(
        1
        for i in range(len(samples) - window_mi)
        if geo.haversine_mi(samples[i], samples[i + window_mi]) < window_mi * min_progress
    )
    return loops / len(samples)


def _is_clean(route: RawRoute) -> bool:
    return _backtrack_ratio(route) <= CLEAN_BACKTRACK and _loop_ratio(route) == 0


def _route_index(route: RawRoute) -> geo.PointIndex:
    cum = geo.cumulative_miles(route.coords)
    return geo.PointIndex(geo.resample(route.coords, cum, 0.5), cell_deg=0.05)


def _via_candidates(base: RawRoute, origin: geo.LonLat, dest: geo.LonLat) -> list[geo.LonLat]:
    """Via points pushed sideways from points along the fastest route.

    Ordered by how likely they are to produce a sensible alternative: a modest
    push at the midpoint first, then larger pushes and off-center positions.
    """
    straight = geo.haversine_mi(origin, dest)
    heading = geo.bearing_deg(origin, dest)
    cum = geo.cumulative_miles(base.coords)
    plan = [(0.5, 0.18), (0.5, 0.30), (0.33, 0.22), (0.67, 0.22), (0.5, 0.45), (0.4, 0.35), (0.6, 0.35)]
    vias = []
    for frac, push in plan:
        anchor, _ = geo.interpolate_along(base.coords, cum, cum[-1] * frac)
        offset = min(150.0, max(3.0, straight * push))
        for side in (90, -90):
            vias.append(geo.offset_point(anchor, heading + side, offset))
    return vias


def _cache_key(origin: geo.LonLat, dest: geo.LonLat) -> str:
    raw = f"{origin[0]:.4f},{origin[1]:.4f};{dest[0]:.4f},{dest[1]:.4f}"
    return "routes:v3:" + hashlib.sha1(raw.encode()).hexdigest()


def get_route_options(origin: geo.LonLat, dest: geo.LonLat) -> list[RawRoute]:
    key = _cache_key(origin, dest)
    cached = cache.get(key)
    if cached is not None:
        return cached

    primary = [_parse_route(r, "osrm") for r in _osrm([origin, dest], alternatives=TARGET_ROUTES)]
    if not primary:
        raise UpstreamError("OSRM", "no drivable route between these points", 422)

    routes = primary[:TARGET_ROUTES]
    indexes = [_route_index(r) for r in routes]
    fastest = min(routes, key=lambda r: r.duration_s)

    if len(routes) < TARGET_ROUTES:
        vias = _via_candidates(fastest, origin, dest)
        # Two concurrent requests: be polite to the public OSRM server.
        with ThreadPoolExecutor(max_workers=2) as pool:
            found = pool.map(lambda v: _safe_osrm([origin, v, dest]), vias)
            candidates = [_parse_route(r[0], "via") for r in found if r]
        candidates = [
            c
            for c in candidates
            if c.duration_s <= fastest.duration_s * MAX_DETOUR_RATIO
            and c.distance_mi <= fastest.distance_mi * MAX_DETOUR_RATIO
            and _backtrack_ratio(c) <= MAX_BACKTRACK
        ]
        # Fill each missing slot with the fastest candidate that is still
        # distinct from every route already chosen, preferring candidates with
        # no doubling back or loops (where a via-point snapped off-route).
        candidates.sort(key=lambda c: (not _is_clean(c), c.duration_s))
        for cand in candidates:
            if len(routes) >= TARGET_ROUTES:
                break
            if _overlap_ratio(cand, indexes) <= MAX_OVERLAP:
                routes.append(cand)
                indexes.append(_route_index(cand))

    routes.sort(key=lambda r: r.duration_s)
    cache.set(key, routes, CACHE_TTL)
    return routes


def _safe_osrm(points: list[geo.LonLat]) -> list[dict]:
    try:
        return _osrm(points)
    except UpstreamError as exc:
        log.warning("via-route candidate failed: %s", exc)
        return []
