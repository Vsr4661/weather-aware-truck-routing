"""Weather risk classification: the spec's threshold table plus the load rules.

Threshold table (per checkpoint):

    Condition | Low        | Moderate  | High      | Severe    | No Travel
    Wind      | <25 mph    | 25-34     | 35-44     | 45-54     | >=55 mph
    Rain      | <0.10 in/h | 0.10-0.25 | 0.25-0.50 | 0.50-1.00 | >1.00
    Snow      | <0.5 in/h  | 0.5-1.0   | 1.0-2.0   | 2.0-3.0   | >3.0

Boundary handling: the table's ranges share endpoints (e.g. 0.25 appears in both
Moderate and High), so each lower bound is inclusive and belongs to the higher
level, except the No Travel cut-offs for rain/snow, which the table states as
strictly greater than (">1.00", ">3.0"). Wind is continuous, so "25-34" means
[25, 35), i.e. 34.6 mph is still Moderate.

Load rules (escalate the wind level, never lower it):

    >=55 mph                 -> No Travel for any load
    45-54 mph and >30,000 lb -> No Travel
    35-44 mph and >40,000 lb -> Severe
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return {
            RiskLevel.LOW: "Low",
            RiskLevel.MODERATE: "Moderate",
            RiskLevel.HIGH: "High",
            RiskLevel.SEVERE: "Severe",
            RiskLevel.NO_TRAVEL: "No Travel",
        }[self]

    @property
    def key(self) -> str:
        return self.name.lower()


def classify_wind(mph: float) -> RiskLevel:
    if mph >= 55:
        return RiskLevel.NO_TRAVEL
    if mph >= 45:
        return RiskLevel.SEVERE
    if mph >= 35:
        return RiskLevel.HIGH
    if mph >= 25:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def classify_rain(in_per_hr: float) -> RiskLevel:
    if in_per_hr > 1.00:
        return RiskLevel.NO_TRAVEL
    if in_per_hr >= 0.50:
        return RiskLevel.SEVERE
    if in_per_hr >= 0.25:
        return RiskLevel.HIGH
    if in_per_hr >= 0.10:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def classify_snow(in_per_hr: float) -> RiskLevel:
    if in_per_hr > 3.0:
        return RiskLevel.NO_TRAVEL
    if in_per_hr >= 2.0:
        return RiskLevel.SEVERE
    if in_per_hr >= 1.0:
        return RiskLevel.HIGH
    if in_per_hr >= 0.5:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def apply_load_rules(wind_mph: float, load_lbs: float) -> tuple[RiskLevel, str | None]:
    """Wind level after the load rules, plus a human-readable note if a rule fired."""
    base = classify_wind(wind_mph)
    if wind_mph >= 55:
        return RiskLevel.NO_TRAVEL, None  # already No Travel from the table
    if 45 <= wind_mph < 55 and load_lbs > 30_000:
        return RiskLevel.NO_TRAVEL, "45–54 mph wind with load over 30,000 lb → No Travel"
    if 35 <= wind_mph < 45 and load_lbs > 40_000:
        return RiskLevel.SEVERE, "35–44 mph wind with load over 40,000 lb → Severe"
    return base, None


@dataclass(frozen=True)
class Assessment:
    level: RiskLevel
    wind_level: RiskLevel
    rain_level: RiskLevel
    snow_level: RiskLevel
    drivers: list[str] = field(default_factory=list)  # which conditions set the level
    load_rule: str | None = None

    def to_dict(self) -> dict:
        return {
            "level": int(self.level),
            "label": self.level.label,
            "wind_level": int(self.wind_level),
            "rain_level": int(self.rain_level),
            "snow_level": int(self.snow_level),
            "drivers": self.drivers,
            "load_rule": self.load_rule,
        }


def assess(wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_lbs: float) -> Assessment:
    """Overall level = worst of (load-adjusted wind, rain, snow)."""
    wind_level, load_rule = apply_load_rules(wind_mph, load_lbs)
    rain_level = classify_rain(rain_in_hr)
    snow_level = classify_snow(snow_in_hr)
    level = max(wind_level, rain_level, snow_level)
    drivers: list[str] = []
    if level > RiskLevel.LOW:
        for name, lvl in (("wind", wind_level), ("rain", rain_level), ("snow", snow_level)):
            if lvl == level:
                drivers.append(name)
    return Assessment(
        level=level,
        wind_level=wind_level,
        rain_level=rain_level,
        snow_level=snow_level,
        drivers=drivers,
        load_rule=load_rule if wind_level == level else None,
    )


def level_code(wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_lbs: float) -> int:
    """Fast path used by the heatmap (thousands of evaluations)."""
    return int(
        max(
            apply_load_rules(wind_mph, load_lbs)[0],
            classify_rain(rain_in_hr),
            classify_snow(snow_in_hr),
        )
    )
