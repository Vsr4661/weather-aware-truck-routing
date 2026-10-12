"""Truck travel-time model: when does the truck reach mile X?

OSRM's public server only has a car profile, so two adjustments make ETAs
realistic for a loaded tractor-trailer:

1. Speed cap: each road segment takes at least ``distance / TRUCK_MAX_MPH``.
   Car-profile durations on interstates assume 70-80 mph; trucks are governed
   (and in several states legally limited) to roughly 65 mph.
2. Hours of Service (optional, FMCSA property-carrying rules): a 30-minute break
   after 8 cumulative hours of driving, and a 10-hour off-duty rest after 11
   hours of driving. Breaks are inserted at the exact point on the route where
   they fall, which shifts every downstream checkpoint ETA, and therefore which
   forecast hour applies there.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from . import geo

TRUCK_MAX_MPH = 65.0
HOS_BREAK_AFTER_S = 8 * 3600
HOS_BREAK_S = 30 * 60
HOS_DRIVE_LIMIT_S = 11 * 3600
HOS_REST_S = 10 * 3600


@dataclass
class Stop:
    kind: str  # "break" | "rest"
    mile: float
    start_s: float  # seconds after departure
    duration_s: float


@dataclass
class Timeline:
    """Piecewise-linear mile -> elapsed-seconds mapping with stop "knots"."""

    knot_miles: list[float]
    knot_seconds: list[float]
    drive_seconds: float
    stops: list[Stop] = field(default_factory=list)

    @property
    def total_miles(self) -> float:
        return self.knot_miles[-1]

    @property
    def total_seconds(self) -> float:
        return self.knot_seconds[-1]

    def seconds_at(self, mile: float) -> float:
        """Elapsed time when the truck is at ``mile`` (after any stop taken there)."""
        return geo.interp_series(self.knot_miles, self.knot_seconds, mile)


def truck_segment_seconds(seg_miles: Sequence[float], seg_seconds: Sequence[float]) -> list[float]:
    return [max(s, mi / TRUCK_MAX_MPH * 3600) for mi, s in zip(seg_miles, seg_seconds, strict=True)]


def build_timeline(seg_miles: Sequence[float], seg_seconds: Sequence[float], hos: bool) -> Timeline:
    seconds = truck_segment_seconds(seg_miles, seg_seconds)
    miles = [0.0]
    elapsed = [0.0]
    stops: list[Stop] = []
    since_break = 0.0  # driving since last 30-min break (or rest)
    since_rest = 0.0  # driving since last 10-h rest
    mile_pos = 0.0
    clock = 0.0

    for seg_mi, seg_s in zip(seg_miles, seconds, strict=True):
        remaining_s = seg_s
        remaining_mi = seg_mi
        while hos and remaining_s > 0:
            until_break = HOS_BREAK_AFTER_S - since_break
            until_rest = HOS_DRIVE_LIMIT_S - since_rest
            until_stop = min(until_break, until_rest)
            if remaining_s <= until_stop:
                break
            # Drive up to the stop point inside this segment.
            frac = until_stop / remaining_s
            part_mi = remaining_mi * frac
            mile_pos += part_mi
            clock += until_stop
            since_break += until_stop
            since_rest += until_stop
            remaining_s -= until_stop
            remaining_mi -= part_mi
            miles.append(mile_pos)
            elapsed.append(clock)
            is_rest = until_rest <= until_break
            duration = HOS_REST_S if is_rest else HOS_BREAK_S
            stops.append(Stop("rest" if is_rest else "break", mile_pos, clock, duration))
            clock += duration
            since_break = 0.0
            if is_rest:
                since_rest = 0.0
            miles.append(mile_pos)
            elapsed.append(clock)
        mile_pos += remaining_mi
        clock += remaining_s
        since_break += remaining_s
        since_rest += remaining_s
        miles.append(mile_pos)
        elapsed.append(clock)

    return Timeline(miles, elapsed, drive_seconds=sum(seconds), stops=stops)
