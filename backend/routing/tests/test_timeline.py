from django.test import SimpleTestCase

from routing.services.timeline import TRUCK_MAX_MPH, build_timeline


def straight_road(hours: float, mph: float = 60.0, seg_minutes: float = 6.0):
    """Uniform road of ``hours`` driving at ``mph``, split into short segments."""
    n = round(hours * 60 / seg_minutes)
    seg_s = seg_minutes * 60
    return [mph * seg_s / 3600] * n, [seg_s] * n


class SpeedCapTests(SimpleTestCase):
    def test_segments_never_faster_than_truck_cap(self):
        # 80 mi in 1 h by car -> truck needs 80 / 65 h.
        tl = build_timeline([80.0], [3600.0], hos=False)
        self.assertAlmostEqual(tl.total_seconds, 80 / TRUCK_MAX_MPH * 3600)

    def test_slow_segments_keep_their_duration(self):
        tl = build_timeline([20.0], [3600.0], hos=False)
        self.assertAlmostEqual(tl.total_seconds, 3600.0)


class HoursOfServiceTests(SimpleTestCase):
    def test_short_trip_has_no_stops(self):
        miles, secs = straight_road(7.5)
        tl = build_timeline(miles, secs, hos=True)
        self.assertEqual(tl.stops, [])
        self.assertAlmostEqual(tl.total_seconds, 7.5 * 3600)

    def test_break_after_eight_hours_then_rest_after_eleven(self):
        miles, secs = straight_road(13)
        tl = build_timeline(miles, secs, hos=True)
        self.assertEqual([s.kind for s in tl.stops], ["break", "rest"])
        brk, rest = tl.stops
        self.assertAlmostEqual(brk.start_s, 8 * 3600)
        self.assertAlmostEqual(brk.mile, 8 * 60)
        # 11 h of driving + the 30 min break
        self.assertAlmostEqual(rest.start_s, 11.5 * 3600)
        self.assertAlmostEqual(rest.mile, 11 * 60)
        self.assertAlmostEqual(tl.total_seconds, 13 * 3600 + 0.5 * 3600 + 10 * 3600)
        self.assertAlmostEqual(tl.drive_seconds, 13 * 3600)

    def test_stops_shift_downstream_etas(self):
        miles, secs = straight_road(10)
        tl = build_timeline(miles, secs, hos=True)
        self.assertAlmostEqual(tl.seconds_at(7 * 60), 7 * 3600)  # before the break
        self.assertAlmostEqual(tl.seconds_at(9 * 60), 9.5 * 3600)  # after the break

    def test_break_mid_segment_is_placed_proportionally(self):
        # One 10-hour segment: the 8h break must land 80% of the way along it.
        tl = build_timeline([600.0], [10 * 3600.0], hos=True)
        self.assertAlmostEqual(tl.stops[0].mile, 480.0)

    def test_hos_disabled(self):
        miles, secs = straight_road(13)
        tl = build_timeline(miles, secs, hos=False)
        self.assertEqual(tl.stops, [])
        self.assertAlmostEqual(tl.total_seconds, 13 * 3600)
