from django.test import SimpleTestCase

from routing.services.recommendation import RouteMetrics, rank, recommend
from routing.services.risk import RiskLevel

NAMES = {"A": "Route A", "B": "Route B", "C": "Route C"}


def metrics(route_id, *, severe=0.0, high=0.0, no_travel=0.0, avg=0.0, hours=10.0):
    return RouteMetrics(
        route_id,
        {
            int(RiskLevel.SEVERE): severe,
            int(RiskLevel.HIGH): high,
            int(RiskLevel.NO_TRAVEL): no_travel,
        },
        avg,
        hours * 3600,
    )


def order(*ms):
    return [m.route_id for m in rank(list(ms))]


class RankingTests(SimpleTestCase):
    def test_fewest_severe_miles_wins_over_everything_else(self):
        a = metrics("A", severe=20, high=0, avg=0.2, hours=8)
        b = metrics("B", severe=0, high=100, avg=1.5, hours=12)
        self.assertEqual(order(a, b), ["B", "A"])

    def test_high_miles_break_severe_ties(self):
        a = metrics("A", severe=10, high=50, hours=8)
        b = metrics("B", severe=10, high=5, hours=12)
        self.assertEqual(order(a, b), ["B", "A"])

    def test_average_risk_breaks_high_ties(self):
        a = metrics("A", high=5, avg=0.6, hours=8)
        b = metrics("B", high=5, avg=0.3, hours=12)
        self.assertEqual(order(a, b), ["B", "A"])

    def test_travel_time_is_last(self):
        a = metrics("A", avg=0.1, hours=12)
        b = metrics("B", avg=0.1, hours=9)
        self.assertEqual(order(a, b), ["B", "A"])

    def test_no_travel_miles_rank_before_severe(self):
        a = metrics("A", no_travel=5, severe=0)
        b = metrics("B", no_travel=0, severe=60)
        self.assertEqual(order(a, b), ["B", "A"])

    def test_sub_mile_noise_does_not_override_time(self):
        a = metrics("A", severe=0.3, hours=8)
        b = metrics("B", severe=0.0, hours=11)
        self.assertEqual(order(a, b), ["A", "B"])


class RecommendTests(SimpleTestCase):
    def test_reason_names_the_deciding_criterion(self):
        rec = recommend([metrics("A", severe=25), metrics("B"), metrics("C", high=10)], NAMES)
        self.assertEqual(rec["route_id"], "B")
        self.assertEqual(rec["ranking"], ["B", "C", "A"])
        self.assertIn("High", rec["reason"])  # B vs runner-up C differs on High miles
        self.assertIn("Severe", rec["comparisons"]["A"])
        self.assertFalse(rec["unsafe"])

    def test_time_reason(self):
        rec = recommend([metrics("A", hours=10), metrics("B", hours=11.5)], NAMES)
        self.assertEqual(rec["route_id"], "A")
        self.assertIn("1h 30m faster", rec["reason"])

    def test_flags_unsafe_when_every_route_has_no_travel(self):
        rec = recommend([metrics("A", no_travel=10), metrics("B", no_travel=30)], NAMES)
        self.assertEqual(rec["route_id"], "A")
        self.assertTrue(rec["unsafe"])


class ToleranceTests(SimpleTestCase):
    def test_small_average_risk_gap_does_not_justify_a_long_detour(self):
        # 25 Moderate miles on ~1,000 mi (avg 0.03) vs a clean route 7 h longer.
        a = metrics("A", avg=0.03, hours=24)
        c = metrics("C", avg=0.0, hours=31)
        self.assertEqual(order(a, c), ["A", "C"])
        rec = recommend([a, c], NAMES)
        self.assertIn("faster", rec["reason"])

    def test_meaningful_average_risk_gap_still_wins(self):
        a = metrics("A", avg=0.35, hours=24)
        c = metrics("C", avg=0.05, hours=31)
        self.assertEqual(order(a, c), ["C", "A"])
