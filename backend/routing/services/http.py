"""Shared HTTP session with retries for third-party APIs."""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class UpstreamError(Exception):
    """A third-party service failed or returned something unusable."""

    def __init__(self, service: str, message: str, status: int = 502):
        super().__init__(f"{service}: {message}")
        self.service = service
        self.message = message
        self.status = status


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.6,
        # 429 is not retried here: rate-limit windows are a minute or longer, and
        # get_json turns it into a clear message instead of a generic RetryError.
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=32)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = settings.HTTP_USER_AGENT
    return session


_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = _build_session()
    return _session


def get_json(service: str, url: str, params: dict | None = None, timeout: float | tuple[float, float] = 20):
    try:
        resp = session().get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise UpstreamError(service, f"request failed ({exc.__class__.__name__})") from exc
    if resp.status_code == 429:
        try:
            reason = resp.json().get("reason", "")
        except ValueError:
            reason = ""
        log.warning("%s rate limited: %s", service, reason or resp.text[:200])
        raise UpstreamError(service, f"rate limit reached ({reason or 'too many requests'}), please retry shortly", 503)
    if resp.status_code >= 400:
        raise UpstreamError(service, f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise UpstreamError(service, "invalid JSON response") from exc
