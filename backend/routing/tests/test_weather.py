from django.test import SimpleTestCase

from routing.services.weather import HourlySeries, aligned_window, snap

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
