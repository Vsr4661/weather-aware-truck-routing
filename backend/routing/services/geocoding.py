"""Place search: Photon (fast, autocomplete-friendly) with a Nominatim fallback."""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.core.cache import cache

from .http import UpstreamError, get_json

CACHE_TTL = 60 * 60 * 24


def _photon_label(props: dict) -> str:
    name = props.get("name") or ""
    street = " ".join(p for p in (props.get("housenumber"), props.get("street")) if p)
    parts = [name or street]
    for key in ("city", "state", "country"):
        value = props.get(key)
        if value and value not in parts:
            parts.append(value)
    return ", ".join(p for p in parts if p)


def _search_photon(query: str, limit: int) -> list[dict]:
    data = get_json(
        "Photon",
        f"{settings.PHOTON_BASE_URL}/api/",
        {"q": query, "limit": limit, "lang": "en"},
        timeout=8,
    )
    results = []
    for feature in data.get("features", []):
        lon, lat = feature["geometry"]["coordinates"]
        results.append({"label": _photon_label(feature.get("properties", {})), "lat": lat, "lon": lon})
    return results


def _search_nominatim(query: str, limit: int) -> list[dict]:
    data = get_json(
        "Nominatim",
        f"{settings.NOMINATIM_BASE_URL}/search",
        {"q": query, "format": "jsonv2", "limit": limit},
        timeout=8,
    )
    return [
        {"label": item.get("display_name", ""), "lat": float(item["lat"]), "lon": float(item["lon"])} for item in data
    ]


def search(query: str, limit: int = 6) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    key = "geo:" + hashlib.sha1(f"{query.lower()}|{limit}".encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        results = _search_photon(query, limit)
    except UpstreamError:
        results = []
    if not results:
        results = _search_nominatim(query, limit)
    # Drop duplicate labels (Photon often returns a city and its boundary).
    seen, unique = set(), []
    for r in results:
        if r["label"] and r["label"] not in seen:
            seen.add(r["label"])
            unique.append(r)
    cache.set(key, unique, CACHE_TTL)
    return unique
