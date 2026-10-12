"""Small, dependency-free geometry helpers.

Coordinates are always (lon, lat) tuples to match GeoJSON / OSRM ordering.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence

EARTH_RADIUS_MI = 3958.7613
METERS_PER_MILE = 1609.344

LonLat = tuple[float, float]


def haversine_mi(a: LonLat, b: LonLat) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def cumulative_miles(coords: Sequence[LonLat]) -> list[float]:
    out = [0.0]
    for i in range(1, len(coords)):
        out.append(out[-1] + haversine_mi(coords[i - 1], coords[i]))
    return out


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def interpolate_along(coords: Sequence[LonLat], cum: Sequence[float], target: float) -> tuple[LonLat, int]:
    """Point at ``target`` miles along the line, plus the index of the segment start."""
    if target <= 0:
        return coords[0], 0
    if target >= cum[-1]:
        return coords[-1], len(coords) - 2
    i = bisect.bisect_right(cum, target) - 1
    seg = cum[i + 1] - cum[i]
    t = 0.0 if seg == 0 else (target - cum[i]) / seg
    a, b = coords[i], coords[i + 1]
    return (lerp(a[0], b[0], t), lerp(a[1], b[1], t)), i


def interp_series(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """Piecewise-linear interpolation of y(x); xs must be non-decreasing."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect.bisect_right(xs, x) - 1
    span = xs[i + 1] - xs[i]
    if span == 0:
        return ys[i]
    return lerp(ys[i], ys[i + 1], (x - xs[i]) / span)


def simplify_indices(coords: Sequence[LonLat], tolerance_deg: float) -> list[int]:
    """Douglas-Peucker simplification; returns the indices of the points kept.

    Works in plain degrees, which is fine for display-level simplification.
    Iterative (no recursion limit issues on 30k+ point cross-country routes).
    """
    n = len(coords)
    if n <= 2:
        return list(range(n))
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    tol2 = tolerance_deg * tolerance_deg
    while stack:
        start, end = stack.pop()
        ax, ay = coords[start]
        bx, by = coords[end]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        best_d2, best_i = -1.0, -1
        for i in range(start + 1, end):
            px, py = coords[i]
            if seg2 == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
                d2 = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d2 > best_d2:
                best_d2, best_i = d2, i
        if best_d2 > tol2:
            keep[best_i] = True
            stack.append((start, best_i))
            stack.append((best_i, end))
    return [i for i, k in enumerate(keep) if k]


def offset_point(origin: LonLat, bearing_deg: float, miles: float) -> LonLat:
    """Destination point given start, bearing and distance (spherical earth)."""
    lon1, lat1 = map(math.radians, origin)
    brng = math.radians(bearing_deg)
    d = miles / EARTH_RADIUS_MI
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brng))
    lon2 = lon1 + math.atan2(
        math.sin(brng) * math.sin(d) * math.cos(lat1), math.cos(d) - math.sin(lat1) * math.sin(lat2)
    )
    return (math.degrees(lon2), math.degrees(lat2))


def bearing_deg(a: LonLat, b: LonLat) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def mercator_y(lat: float) -> float:
    lat = max(-85.0, min(85.0, lat))
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def inverse_mercator_y(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


class PointIndex:
    """Uniform grid bucket index for "is anything within R miles?" queries.

    Used to test which heatmap cells fall inside the route corridor and how much
    two route polylines overlap, without an O(n*m) scan.
    """

    def __init__(self, points: Sequence[LonLat], cell_deg: float):
        self.cell = cell_deg
        self.buckets: dict[tuple[int, int], list[LonLat]] = {}
        for p in points:
            self.buckets.setdefault(self._key(p), []).append(p)

    def _key(self, p: LonLat) -> tuple[int, int]:
        return (math.floor(p[0] / self.cell), math.floor(p[1] / self.cell))

    def any_within(self, p: LonLat, max_mi: float) -> bool:
        """True if any indexed point lies within ``max_mi`` of ``p``.

        Uses a flat-earth distance, accurate to well under 1% at corridor scales.
        """
        lat_cells = math.ceil((max_mi / 69.0) / self.cell)
        kx_scale = 69.0 * max(0.1, math.cos(math.radians(p[1])))
        lon_cells = math.ceil((max_mi / kx_scale) / self.cell)
        kx, ky = self._key(p)
        r2 = max_mi * max_mi
        for dx in range(-lon_cells, lon_cells + 1):
            for dy in range(-lat_cells, lat_cells + 1):
                for q in self.buckets.get((kx + dx, ky + dy), ()):
                    ex = (q[0] - p[0]) * kx_scale
                    ey = (q[1] - p[1]) * 69.0
                    if ex * ex + ey * ey <= r2:
                        return True
        return False


def resample(coords: Sequence[LonLat], cum: Sequence[float], step_mi: float) -> list[LonLat]:
    """Points every ``step_mi`` along the line (always includes both ends)."""
    total = cum[-1]
    if total == 0:
        return [coords[0]]
    n = max(1, math.ceil(total / step_mi))
    return [interpolate_along(coords, cum, total * k / n)[0] for k in range(n + 1)]
