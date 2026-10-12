from django.test import SimpleTestCase

from routing.services.risk import (
    RiskLevel,
    apply_load_rules,
    assess,
    classify_rain,
    classify_snow,
    classify_wind,
)

L, M, H, S, NT = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)


class ThresholdTableTests(SimpleTestCase):
    def test_wind_bands(self):
        cases = [
            (0, L),
            (24.9, L),
            (25, M),
            (34, M),
            (34.9, M),
            (35, H),
            (44.9, H),
            (45, S),
            (54.9, S),
            (55, NT),
            (80, NT),
        ]
        for mph, expected in cases:
            with self.subTest(mph=mph):
                self.assertEqual(classify_wind(mph), expected)

    def test_rain_bands(self):
        cases = [(0, L), (0.099, L), (0.10, M), (0.249, M), (0.25, H), (0.49, H), (0.50, S), (1.00, S), (1.01, NT)]
        for rate, expected in cases:
            with self.subTest(rate=rate):
                self.assertEqual(classify_rain(rate), expected)

    def test_snow_bands(self):
        cases = [(0, L), (0.49, L), (0.5, M), (0.99, M), (1.0, H), (1.99, H), (2.0, S), (3.0, S), (3.01, NT)]
        for rate, expected in cases:
            with self.subTest(rate=rate):
                self.assertEqual(classify_snow(rate), expected)


class LoadRuleTests(SimpleTestCase):
    def test_55_mph_is_no_travel_for_any_load(self):
        for load in (0, 10_000, 80_000):
            self.assertEqual(apply_load_rules(55, load)[0], NT)

    def test_45_to_54_over_30k_is_no_travel(self):
        self.assertEqual(apply_load_rules(45, 30_001)[0], NT)
        self.assertEqual(apply_load_rules(54.9, 45_000)[0], NT)
        # exactly 30,000 lb is not "> 30,000"
        self.assertEqual(apply_load_rules(50, 30_000)[0], S)

    def test_35_to_44_over_40k_is_severe(self):
        self.assertEqual(apply_load_rules(35, 40_001)[0], S)
        self.assertEqual(apply_load_rules(44.9, 80_000)[0], S)
        self.assertEqual(apply_load_rules(40, 40_000)[0], H)
        self.assertEqual(apply_load_rules(40, 35_000)[0], H)

    def test_load_rule_does_not_apply_below_35(self):
        self.assertEqual(apply_load_rules(34.9, 80_000)[0], M)

    def test_rule_note_is_reported(self):
        level, note = apply_load_rules(48, 35_000)
        self.assertEqual(level, NT)
        self.assertIn("30,000", note)


class AssessTests(SimpleTestCase):
    def test_overall_is_worst_condition(self):
        a = assess(wind_mph=10, rain_in_hr=0.3, snow_in_hr=0.6, load_lbs=20_000)
        self.assertEqual(a.level, H)
        self.assertEqual(a.drivers, ["rain"])

    def test_load_adjusted_wind_drives_level(self):
        a = assess(wind_mph=38, rain_in_hr=0.3, snow_in_hr=0, load_lbs=42_000)
        self.assertEqual(a.level, S)
        self.assertEqual(a.drivers, ["wind"])
        self.assertIsNotNone(a.load_rule)

    def test_ties_list_every_driver(self):
        a = assess(wind_mph=30, rain_in_hr=0.12, snow_in_hr=0.7, load_lbs=0)
        self.assertEqual(a.level, M)
        self.assertEqual(a.drivers, ["wind", "rain", "snow"])

    def test_calm_weather_has_no_drivers(self):
        a = assess(5, 0, 0, 80_000)
        self.assertEqual(a.level, L)
        self.assertEqual(a.drivers, [])
