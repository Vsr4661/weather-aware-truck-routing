from datetime import UTC, datetime
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from routing.services import weather
from routing.services.http import UpstreamError
from routing.services.weather import HourlySeries, aligned_window, parse_met, snap

T0 = 1_800_000_000 - (1_800_000_000 % 3600)  # an exact hour


def series():
    return HourlySeries(
        times=[T0, T0 + 3600, T0 + 7200],
        wind=[10.0, 30.0, 50.0],
        gust=[20.0, 40.0, 60.0],
        rain=[0.0, 0.2, 0.6],  # bucket at T0+3600 covers T0..T0+3600
        snow=[0.0, 0.0, 1.5],
        temp=[30.0, 32.0, 34.0],
        code=[0, 61, 63],
    )


class SamplingTests(SimpleTestCase):
    def test_wind_is_interpolated_between_hours(self):
        wx = series().at(T0 + 1800)
        self.assertAlmostEqual(wx["wind_mph"], 20.0)
        self.assertAlmostEqual(wx["gust_mph"], 30.0)

    def test_precip_uses_the_hour_bucket_containing_the_eta(self):
        # 00:30 lies in the hour ending 01:00 -> second bucket.
        self.assertAlmostEqual(series().at(T0 + 1800)["rain_in_hr"], 0.2)
        # 01:20 lies in the hour ending 02:00 -> third bucket.
        wx = series().at(T0 + 4800)
        self.assertAlmostEqual(wx["rain_in_hr"], 0.6)
        self.assertAlmostEqual(wx["snow_in_hr"], 1.5)

    def test_exact_hour_uses_the_bucket_ending_then(self):
        self.assertAlmostEqual(series().at(T0 + 3600)["rain_in_hr"], 0.2)

    def test_out_of_range_clamps(self):
        self.assertAlmostEqual(series().at(T0 + 99_999)["wind_mph"], 50.0)


class HelperTests(SimpleTestCase):
    def test_snap_rounds_to_grid(self):
        self.assertEqual(snap((-87.6298, 41.8781)), (-87.65, 41.9))

    def test_window_is_aligned_and_covers_range(self):
        start, end = aligned_window(T0 + 100, T0 + 30_000)
        self.assertLessEqual(start, T0 + 100)
        self.assertGreaterEqual(end, T0 + 30_000 + 3600)
        self.assertEqual(start % (6 * 3600), 0)
        self.assertEqual(end % (6 * 3600), 0)


def met_step(ts, wind_ms, temp_c, block=None):
    data = {"instant": {"details": {"wind_speed": wind_ms, "air_temperature": temp_c}}}
    if block:
        key, mm, symbol = block
        data[key] = {"summary": {"symbol_code": symbol}, "details": {"precipitation_amount": mm}}
    return {"time": datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z"), "data": data}


class MetNorwayParserTests(SimpleTestCase):
    def setUp(self):
        steps = [
            met_step(T0, 10.0, 5.0, ("next_1_hours", 2.54, "rain")),  # 0.1 in liquid
            met_step(T0 + 3600, 20.0, 5.0, ("next_6_hours", 6 * 25.4 / 10, "heavysnow")),
            met_step(T0 + 7 * 3600, 20.0, -2.0, ("next_6_hours", 0.0, "cloudy")),
        ]
        self.series = parse_met({"properties": {"timeseries": steps}}, T0, T0 + 8 * 3600)

    def test_wind_converted_to_mph_and_interpolated(self):
        self.assertAlmostEqual(self.series.at(T0)["wind_mph"], 22.37, places=1)
        self.assertAlmostEqual(self.series.at(T0 + 1800)["wind_mph"], (22.37 + 44.74) / 2, places=1)

    def test_one_hour_rain_block(self):
        wx = self.series.at(T0 + 1800)  # inside T0..T0+1h
        self.assertAlmostEqual(wx["rain_in_hr"], 0.1, places=3)
        self.assertEqual(wx["snow_in_hr"], 0)

    def test_six_hour_snow_block_is_spread_and_converted_10_to_1(self):
        wx = self.series.at(T0 + 3 * 3600 + 600)
        # 15.24 mm over 6 h = 0.1 in/hr of liquid = 1.0 in/hr of snow at 10:1
        self.assertAlmostEqual(wx["snow_in_hr"], 1.0, places=2)
        self.assertEqual(wx["rain_in_hr"], 0)
        self.assertEqual(wx["weather_code"], 73)

    def test_temperature_in_fahrenheit(self):
        self.assertAlmostEqual(self.series.at(T0)["temp_f"], 41.0, places=1)


class FallbackTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_falls_back_to_met_when_open_meteo_refuses(self):
        refused = UpstreamError("Open-Meteo", "rate limit reached", 503)
        with (
            mock.patch.object(weather, "_fetch_open_meteo", side_effect=refused) as om,
            mock.patch.object(weather, "_fetch_met", return_value=[series()]) as met,
        ):
            out = weather.fetch_hourly([(-100.0, 40.0)], T0, T0 + 3600)
            self.assertIn((-100.0, 40.0), out)
            self.assertEqual(met.call_count, 1)
            # Open-Meteo is skipped while it is known to be down.
            weather.fetch_hourly([(-101.0, 40.0)], T0, T0 + 3600)
            self.assertEqual(om.call_count, 1)
            self.assertEqual(met.call_count, 2)
