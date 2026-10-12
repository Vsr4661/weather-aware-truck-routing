"""Route ranking, in the spec's order of preference:

    1. Fewest Severe miles
    2. Fewest High miles
    3. Lowest average risk
    4. Shortest travel time

One addition: miles rated *No Travel* are compared before everything else. The
spec's table defines No Travel as worse than Severe, so a route that crosses a
No Travel zone must never beat one that does not just because it has fewer
Severe miles.

Tolerances ("balancing weather risk and travel time"): each criterion only
decides when the difference is meaningful; otherwise the next one is consulted.

* Miles at a level: differences of 1 mile or less are noise (checkpoint
  spacing alone shifts mileage by fractions of a mile).
* Average risk: differences of 0.10 or less are treated as equal. 0.10 is
  e.g. 10% of the route at Moderate. Without this, 25 Moderate miles on a
  1,000-mile trip (avg 0.03 vs 0.00) would justify a 7-hour detour.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cmp_to_key

from .risk import RiskLevel

MILE_TOLERANCE = 1.0
AVG_RISK_TOLERANCE = 0.10


@dataclass(frozen=True)
class RouteMetrics:
    route_id: str
    miles_by_level: dict[int, float]  # RiskLevel -> miles
    avg_risk: float  # mile-weighted mean of level (0 = Low ... 4 = No Travel)
    duration_s: float  # total trip time including mandatory stops

    def miles(self, level: RiskLevel) -> float:
        return self.miles_by_level.get(int(level), 0.0)


@dataclass(frozen=True)
class Criterion:
    name: str
    value: Callable[[RouteMetrics], float]
    tolerance: float


CRITERIA = [
    Criterion("No Travel", lambda m: m.miles(RiskLevel.NO_TRAVEL), MILE_TOLERANCE),
    Criterion("Severe", lambda m: m.miles(RiskLevel.SEVERE), MILE_TOLERANCE),
    Criterion("High", lambda m: m.miles(RiskLevel.HIGH), MILE_TOLERANCE),
    Criterion("average risk", lambda m: m.avg_risk, AVG_RISK_TOLERANCE),
    Criterion("travel time", lambda m: m.duration_s, 0.0),
]
# The first three criteria are the "hard" risk ones (mileage in dangerous weather).
HARD_RISK_CRITERIA = 3


def deciding(a: RouteMetrics, b: RouteMetrics, depth: int = len(CRITERIA)) -> tuple[int, int]:
    """(criterion index, sign) of the first criterion that separates a and b.

    sign < 0 means ``a`` is better. Returns (-1, 0) if they are equivalent.
    """
    for i, c in enumerate(CRITERIA[:depth]):
        diff = c.value(a) - c.value(b)
        if abs(diff) > c.tolerance:
            return i, (-1 if diff < 0 else 1)
    return -1, 0


def compare(a: RouteMetrics, b: RouteMetrics, depth: int = len(CRITERIA)) -> int:
    return deciding(a, b, depth)[1]


def rank(metrics: list[RouteMetrics]) -> list[RouteMetrics]:
    return sorted(metrics, key=cmp_to_key(compare))


def _fmt_duration(seconds: float) -> str:
    total_min = round(seconds / 60)
    h, m = divmod(total_min, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def explain(best: RouteMetrics, other: RouteMetrics, names: dict[str, str]) -> str:
    """Why ``best`` ranks above ``other``: the first criterion that separates them."""
    bn, on = names[best.route_id], names[other.route_id]
    idx, _ = deciding(best, other)
    if idx < 0:
        return f"{bn} and {on} are equivalent on risk and time."
    crit = CRITERIA[idx]
    if idx < HARD_RISK_CRITERIA:
        return f"{bn} has {crit.value(best):.0f} {crit.name}-risk miles vs {crit.value(other):.0f} on {on}."
    if crit.name == "average risk":
        return (
            f"Same Severe/High mileage as {on}, but lower average risk ({best.avg_risk:.2f} vs {other.avg_risk:.2f})."
        )
    diff = other.duration_s - best.duration_s
    return f"Weather risk is equivalent to {on}; {bn} is {_fmt_duration(diff)} faster."


def recommend(metrics: list[RouteMetrics], names: dict[str, str]) -> dict:
    ordered = rank(metrics)
    best = ordered[0]
    return {
        "route_id": best.route_id,
        "ranking": [m.route_id for m in ordered],
        "reason": explain(best, ordered[1], names) if len(ordered) > 1 else "Only one route found.",
        "comparisons": {m.route_id: explain(best, m, names) for m in ordered[1:]},
        "unsafe": best.miles(RiskLevel.NO_TRAVEL) > 0,
    }
