"""Hourly forecasts from Open-Meteo, sampled at the truck's arrival time.

Units requested from the API: wind in mph, precipitation and snowfall in inches.

Open-Meteo semantics that matter for correctness:
* ``wind_speed_10m`` / ``wind_gusts_10m`` are instantaneous values *at* the
  timestamp, so we interpolate linearly between the two surrounding hours.
* ``rain``, ``showers`` and ``snowfall`` are sums over the *preceding* hour, so
  an hourly sum is directly an in/hr rate and the bucket labelled ``HH:00``
  covers ``HH-1:00 .. HH:00``. A truck passing at 14:20 uses the 15:00 bucket.
* Liquid rain is ``rain`` (large-scale) + ``showers`` (convective); Open-Meteo
  reports them separately, and ignoring showers would miss thunderstorms.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

from django.conf import settings
from django.core.cache import cache

from . import geo
from .http import UpstreamError, get_json

log = logging.getLogger(__name__)

HOURLY_VARS = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall,temperature_2m,weather_code"
CHUNK_SIZE = 50  # locations per request: small enough to parallelise, URL well under limits
WINDOW_ALIGN_S = 6 * 3600  # align fetch windows so repeat plans hit the cache
CACHE_TTL = 30 * 60
MAX_WORKERS = 6


def snap(p: geo.LonLat, precision: float = 0.05) -> geo.LonLat:
    """Round a point to a grid (~3.5 mi) so nearby checkpoints share a forecast.

    Forecast models behind Open-Meteo run at ~2-13 km resolution, so this does
    not lose information but de-duplicates overlapping route alternatives.
    """
    return (round(round(p[0] / precision) * precision, 4), round(round(p[1] / precision) * precision, 4))


@dataclass
class HourlySeries:
    times: list[int]  # unix seconds, hourly, UTC
    wind: list[float]
    gust: list[float]
    rain: list[float]  # rain + showers, in/hr
    snow: list[float]  # in/hr
    temp: list[float]  # deg F
    code: list[int]  # WMO weather code

    def _index_floor(self, ts: float) -> int:
        i = int((ts - self.times[0]) // 3600)
        return max(0, min(len(self.times) - 1, i))

    def at(self, ts: float) -> dict:
        """Conditions at an arbitrary instant (see module docstring)."""
        i0 = self._index_floor(ts)
        i1 = min(i0 + 1, len(self.times) - 1)
        frac = 0.0 if i1 == i0 else max(0.0, min(1.0, (ts - self.times[i0]) / 3600))
        # Precip bucket labelled at the end of the hour containing ts.
        bucket = min(len(self.times) - 1, i0 + 1) if ts > self.times[i0] else i0
        return {
            "wind_mph": geo.lerp(self.wind[i0], self.wind[i1], frac),
            "gust_mph": geo.lerp(self.gust[i0], self.gust[i1], frac),
            "rain_in_hr": self.rain[bucket],
            "snow_in_hr": self.snow[bucket],
            "temp_f": geo.lerp(self.temp[i0], self.temp[i1], frac),
            "weather_code": self.code[bucket],
        }

    def covers(self, ts: float) -> bool:
        return self.times[0] <= ts <= self.times[-1] + 3600


def _num(values: list, default: float = 0.0) -> list[float]:
    return [default if v is None else float(v) for v in values]


def _parse(item: dict) -> HourlySeries:
    h = item["hourly"]
    rain = _num(h["rain"])
    showers = _num(h.get("showers", [0] * len(rain)))
    return HourlySeries(
        times=[int(t) for t in h["time"]],
        wind=_num(h["wind_speed_10m"]),
        gust=_num(h["wind_gusts_10m"]),
        rain=[r + s for r, s in zip(rain, showers, strict=True)],
        snow=_num(h["snowfall"]),
        temp=_num(h["temperature_2m"]),
        code=[int(c) for c in _num(h["weather_code"])],
    )


def _iso_hour(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M")


def _fetch_chunk(points: list[geo.LonLat], start: int, end: int) -> list[HourlySeries]:
    params = {
        "latitude": ",".join(f"{p[1]:.4f}" for p in points),
        "longitude": ",".join(f"{p[0]:.4f}" for p in points),
        "hourly": HOURLY_VARS,
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "temperature_unit": "fahrenheit",
        "timeformat": "unixtime",
        "timezone": "GMT",
        "start_hour": _iso_hour(start),
        "end_hour": _iso_hour(end),
    }
    if settings.OPEN_METEO_API_KEY:
        params["apikey"] = settings.OPEN_METEO_API_KEY
    data = get_json("Open-Meteo", f"{settings.OPEN_METEO_BASE_URL}/v1/forecast", params, timeout=(5, 12))
    if isinstance(data, dict):
        if data.get("error"):
            raise UpstreamError("Open-Meteo", data.get("reason", "forecast request failed"), 422)
        data = [data]
    if len(data) != len(points):
        raise UpstreamError("Open-Meteo", "unexpected number of locations in response")
    return [_parse(item) for item in data]


def aligned_window(start_ts: float, end_ts: float) -> tuple[int, int]:
    start = int(math.floor(start_ts / WINDOW_ALIGN_S) * WINDOW_ALIGN_S)
    end = int(math.ceil((end_ts + 3600) / WINDOW_ALIGN_S) * WINDOW_ALIGN_S)
    return start, end


def fetch_hourly(points: Iterable[geo.LonLat], start_ts: float, end_ts: float) -> dict[geo.LonLat, HourlySeries]:
    """Hourly series for each (already snapped) point covering [start_ts, end_ts]."""
    start, end = aligned_window(start_ts, end_ts)
    unique = list(dict.fromkeys(points))
    result: dict[geo.LonLat, HourlySeries] = {}
    keys = {p: f"wx:v1:{p[0]:.4f},{p[1]:.4f}:{start}:{end}" for p in unique}
    cached = cache.get_many(list(keys.values()))
    missing = []
    for p in unique:
        hit = cached.get(keys[p])
        if hit is not None:
            result[p] = hit
        else:
            missing.append(p)

    chunks = [missing[i : i + CHUNK_SIZE] for i in range(0, len(missing), CHUNK_SIZE)]
    if chunks:
        log.info("Open-Meteo: %d cached, fetching %d in %d requests", len(result), len(missing), len(chunks))
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for chunk, series in zip(chunks, pool.map(lambda c: _fetch_chunk(c, start, end), chunks), strict=True):
                fresh = dict(zip(chunk, series, strict=True))
                result.update(fresh)
                cache.set_many({keys[p]: s for p, s in fresh.items()}, CACHE_TTL)
    return result
