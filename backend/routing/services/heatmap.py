"""Weather heatmap over the trip corridor, hourly for 0-48 h after departure.

The grid is regular in Web-Mercator space (equal steps in x and in mercator-y)
so the frontend can paint it into a canvas and drop it on the map as a single
image overlay with no reprojection. Only cells within ``CORRIDOR_MI`` of any
route are fetched; everything else is transparent.

The number of cells is capped (each forecast location costs one Open-Meteo
API call), and the cell size grows with trip length to stay under the cap.
"""

from __future__ import annotations

import math

from . import geo, weather
from .risk import level_code

CORRIDOR_MI = 40.0
MAX_CELLS = 160
MIN_CELL_MI = 8.0
HOURS = 48


def _corridor_index(paths: list[list[list[float]]], step_mi: float) -> geo.PointIndex:
    samples: list[geo.LonLat] = []
    for path in paths:
        coords = [tuple(p) for p in path]
        samples.extend(geo.resample(coords, geo.cumulative_miles(coords), step_mi))
    return geo.PointIndex(samples, cell_deg=0.25)


def _build_grid(paths, corridor_mi: float):
    lons = [p[0] for path in paths for p in path]
    lats = [p[1] for path in paths for p in path]
    pad_lat = corridor_mi / 69.0
    mid_lat = (min(lats) + max(lats)) / 2
    pad_lon = corridor_mi / (69.0 * max(0.2, math.cos(math.radians(mid_lat))))
    west, east = min(lons) - pad_lon, max(lons) + pad_lon
    south, north = min(lats) - pad_lat, max(lats) + pad_lat

    route_len = max(geo.cumulative_miles([tuple(p) for p in path])[-1] for path in paths)
    # Rough corridor area (union of routes is between 1x and 3x the longest).
    est_area = route_len * 1.6 * 2 * corridor_mi + math.pi * corridor_mi**2
    cell_mi = max(MIN_CELL_MI, math.sqrt(est_area / MAX_CELLS))

    index = _corridor_index(paths, step_mi=2.0)
    y_south, y_north = geo.mercator_y(south), geo.mercator_y(north)
    while True:
        # Cell width in degrees of longitude at mid-latitude; mercator-y step
        # chosen so the cell is roughly square on the ground there.
        dlon = cell_mi / (69.0 * math.cos(math.radians(mid_lat)))
        cols = max(2, math.ceil((east - west) / dlon))
        dy = math.radians(dlon)  # mercator: equal x/y steps give square cells
        rows = max(2, math.ceil((y_north - y_south) / dy))
        cells, centers = [], []
        for r in range(rows):
            lat = geo.inverse_mercator_y(y_north - (r + 0.5) * (y_north - y_south) / rows)
            for c in range(cols):
                lon = west + (c + 0.5) * (east - west) / cols
                if index.any_within((lon, lat), corridor_mi):
                    cells.append(r * cols + c)
                    centers.append((lon, lat))
        if len(cells) <= MAX_CELLS:
            break
        cell_mi *= 1.15
    return {
        "bbox": [west, south, east, north],
        "cols": cols,
        "rows": rows,
        "cell_mi": round(cell_mi, 1),
        "cells": cells,
    }, centers


def build_heatmap(paths: list[list[list[float]]], departure_ts: float, load_lbs: float) -> dict:
    grid, centers = _build_grid(paths, CORRIDOR_MI)
    start = math.floor(departure_ts / 3600) * 3600
    times = [start + h * 3600 for h in range(HOURS + 1)]
    snapped = [weather.snap(c) for c in centers]
    series = weather.fetch_hourly(snapped, times[0], times[-1])

    risk, wind, gust, rain, snow = [], [], [], [], []
    for ts in times:
        r_row, w_row, g_row, rn_row, s_row = [], [], [], [], []
        for p in snapped:
            wx = series[p].at(ts)
            w_row.append(round(wx["wind_mph"], 1))
            g_row.append(round(wx["gust_mph"], 1))
            rn_row.append(round(wx["rain_in_hr"], 3))
            s_row.append(round(wx["snow_in_hr"], 3))
            r_row.append(level_code(wx["wind_mph"], wx["rain_in_hr"], wx["snow_in_hr"], load_lbs))
        risk.append(r_row)
        wind.append(w_row)
        gust.append(g_row)
        rain.append(rn_row)
        snow.append(s_row)

    return {
        **grid,
        "times": times,
        "corridor_mi": CORRIDOR_MI,
        "layers": {"risk": risk, "wind": wind, "gust": gust, "rain": rain, "snow": snow},
    }
