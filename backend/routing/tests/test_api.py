from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from routing.services.http import UpstreamError


def plan_body(**overrides):
    body = {
        "origin": {"label": "Chicago", "lat": 41.88, "lon": -87.63},
        "destination": {"label": "Denver", "lat": 39.74, "lon": -104.98},
        "departure": (timezone.now() + timedelta(hours=1)).isoformat(),
        "load_lbs": 42000,
        "interval_mi": 25,
        "hos": True,
    }
    body.update(overrides)
    return body


class PlanEndpointTests(SimpleTestCase):
    def setUp(self):
        cache.clear()  # reset throttle counters
        self.client = APIClient()

    def test_valid_request_reaches_planner(self):
        with mock.patch("routing.views.planner.build_plan", return_value={"ok": True}) as build:
            res = self.client.post("/api/plan", plan_body(), format="json")
        self.assertEqual(res.status_code, 200)
        req = build.call_args.args[0]
        self.assertEqual(req.origin, (-87.63, 41.88))  # (lon, lat)
        self.assertEqual(req.interval_mi, 25)

    def test_rejects_bad_input(self):
        res = self.client.post(
            "/api/plan",
            plan_body(interval_mi=15, load_lbs=-1, departure="2001-01-01T00:00:00Z"),
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(set(res.data), {"interval_mi", "load_lbs", "departure"})

    def test_rejects_departure_beyond_forecast_range(self):
        far = (timezone.now() + timedelta(days=9)).isoformat()
        res = self.client.post("/api/plan", plan_body(departure=far), format="json")
        self.assertEqual(res.status_code, 400)

    def test_upstream_failure_is_reported(self):
        err = UpstreamError("OSRM", "no drivable route between these points", 422)
        with mock.patch("routing.views.planner.build_plan", side_effect=err):
            res = self.client.post("/api/plan", plan_body(), format="json")
        self.assertEqual(res.status_code, 422)
        self.assertIn("OSRM", res.data["detail"])


class HeatmapEndpointTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_passes_paths_through(self):
        body = {
            "paths": [[[-100, 40], [-99, 40]]],
            "departure": timezone.now().isoformat(),
            "load_lbs": 10000,
        }
        with mock.patch("routing.views.heatmap.build_heatmap", return_value={"ok": True}) as build:
            res = self.client.post("/api/heatmap", body, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(build.call_args.args[0], [[[-100.0, 40.0], [-99.0, 40.0]]])

    def test_rejects_out_of_range_coordinates(self):
        body = {"paths": [[[-200, 40], [-99, 40]]], "departure": timezone.now().isoformat(), "load_lbs": 0}
        res = self.client.post("/api/heatmap", body, format="json")
        self.assertEqual(res.status_code, 400)
