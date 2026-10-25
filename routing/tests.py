from django.test import SimpleTestCase

from .planner import NoFuelStopError, plan_stops


def st(miles, price):
    return {"miles": miles, "price": price}


class PlannerTests(SimpleTestCase):
    def test_short_trip_needs_no_stops(self):
        self.assertEqual(plan_stops([st(100, 3.5)], 300), [])

    def test_long_trip_buys_the_right_amount(self):
        stations = [st(100, 3.5), st(300, 3.0), st(450, 4.0),
                    st(700, 3.2), st(900, 2.9), st(1100, 3.8)]
        stops = plan_stops(stations, 1200)
        self.assertEqual([s["miles"] for s in stops], [300, 700, 900])
        # 1200 miles at 10 mpg = 120 gal, minus the 50 gal already in the starting tank
        self.assertAlmostEqual(sum(s["gallons"] for s in stops), 70)
        self.assertAlmostEqual(sum(s["cost"] for s in stops), 209.0)

    def test_gap_too_big_raises(self):
        with self.assertRaises(NoFuelStopError):
            plan_stops([st(100, 3.0)], 1200)
            