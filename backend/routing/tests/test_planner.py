"""Planner tests with routing and weather stubbed out (no network)."""

from datetime import UTC, datetime
from unittest import mock

from django.test import SimpleTestCase

from routing.services import geo, planner
from routing.services.routing import RawRoute
from routing.services.weather import HourlySeries

DEPARTURE = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
DEP_TS = int(DEPARTURE.timestamp())


def line_route(lat: float, miles: float, hours: float) -> RawRoute:
    """Due-east route starting at (-100, lat), split into 1-mile segments."""
    n = int(miles)
    start = (-100.0, lat)
    coords = [start] + [geo.offset_point(start, 90, k + 1) for k in range(n)]
    seg_miles = [geo.haversine_mi(coords[i], coords[i + 1]) for i in range(n)]
    seg_s = [hours * 3600 / n] * n
    return RawRoute(coords, seg_miles, seg_s, sum(seg_miles), hours * 3600, ["I 1"], "osrm")


def weather_stub(storm_lat: float | None, storm_until_h: float = 1e9):
    """Calm everywhere, except 40 mph wind on points near ``storm_lat`` until a given hour."""

    def fetch(points, start_ts, end_ts):
        hours = int((end_ts - DEP_TS) // 3600) + 30
        times = [DEP_TS + h * 3600 for h in range(-2, hours)]
        out = {}
        for p in points:
            stormy = storm_lat is not None and abs(p[1] - storm_lat) < 0.2
            wind = [40.0 if stormy and (t - DEP_TS) / 3600 < storm_until_h else 5.0 for t in times]
            zeros = [0.0] * len(times)
            out[p] = HourlySeries(times, wind, wind, zeros, zeros, zeros, [0] * len(times))
        return out

    return fetch


def plan_with(routes, fetch, **overrides):
    req = planner.PlanRequest(
        origin=(-100.0, 40.0),
        destination=(-98.0, 40.0),
        origin_label="O",
        destination_label="D",
        departure=DEPARTURE,
        load_lbs=overrides.get("load_lbs", 42_000),
        interval_mi=overrides.get("interval_mi", 10),
        hos=overrides.get("hos", True),
    )
    with (
        mock.patch.object(planner.routing, "get_route_options", return_value=routes),
        mock.patch.object(planner.weather, "fetch_hourly", side_effect=fetch),
    ):
        return planner.build_plan(req)


class CheckpointTests(SimpleTestCase):
    def test_checkpoint_marks(self):
        self.assertEqual(planner.checkpoint_miles(100, 25), [0, 25, 50, 75, 100])
        self.assertEqual(planner.checkpoint_miles(105, 25), [0, 25, 50, 75, 100, 105])
        # a regular mark within a mile of the destination merges into it
        self.assertEqual(planner.checkpoint_miles(100.4, 25), [0, 25, 50, 75, 100.4])

    def test_owned_miles_cover_route_exactly(self):
        plan = plan_with([line_route(40, 123, 2)], weather_stub(None), interval_mi=25)
        cps = plan["routes"][0]["checkpoints"]
        self.assertEqual([c["mile"] for c in cps][:3], [0, 25, 50])
        self.assertAlmostEqual(sum(c["owned_miles"] for c in cps), plan["routes"][0]["distance_mi"], places=0)

    def test_etas_follow_the_truck(self):
        plan = plan_with([line_route(40, 120, 2)], weather_stub(None), interval_mi=10)
        cps = plan["routes"][0]["checkpoints"]
        # 120 mi in 2 h = 60 mph (under the cap), so mile 60 is reached after 1 h.
        mile60 = next(c for c in cps if c["mile"] == 60)
        self.assertAlmostEqual(mile60["elapsed_s"], 3600, delta=5)


class RecommendationIntegrationTests(SimpleTestCase):
    def setUp(self):
        self.routes = [line_route(40.0, 200, 3.0), line_route(41.0, 210, 3.3), line_route(42.0, 230, 3.6)]

    def test_heavy_load_in_high_wind_is_severe_and_avoided(self):
        plan = plan_with(self.routes, weather_stub(storm_lat=40.0))
        a = plan["routes"][0]
        self.assertEqual(a["metrics"]["max_level"], 3)  # 40 mph + 42,000 lb -> Severe
        self.assertGreater(a["metrics"]["miles_by_level"]["severe"], 150)
        self.assertEqual(plan["recommendation"]["route_id"], "B")
        self.assertIn("Severe", plan["recommendation"]["comparisons"]["A"])

    def test_light_load_same_wind_is_only_high(self):
        plan = plan_with(self.routes, weather_stub(storm_lat=40.0), load_lbs=20_000)
        self.assertEqual(plan["routes"][0]["metrics"]["max_level"], 2)

    def test_calm_weather_picks_fastest(self):
        plan = plan_with(self.routes, weather_stub(None))
        self.assertEqual(plan["recommendation"]["route_id"], "A")
        self.assertIsNone(plan["departure_advice"])

    def test_departure_advice_when_storm_clears(self):
        # Storm on every route until hour 3: leaving later avoids it entirely.
        routes = [line_route(40.0, 200, 3.0)]
        plan = plan_with(routes, weather_stub(storm_lat=40.0, storm_until_h=3))
        advice = plan["departure_advice"]
        self.assertIsNotNone(advice)
        self.assertEqual(advice["offset_h"], 4)  # first scan step after the storm
        self.assertEqual(advice["miles_by_level"]["severe"], 0)

    def test_segments_and_path_are_consistent(self):
        plan = plan_with(self.routes, weather_stub(storm_lat=40.0))
        route = plan["routes"][0]
        self.assertEqual(len(route["path"]), len(route["path_s"]))
        self.assertEqual(route["path_s"], sorted(route["path_s"]))
        self.assertAlmostEqual(route["segments"][-1]["to_mile"], route["distance_mi"], places=0)
