import json
import unittest
from datetime import date, timedelta
from pathlib import Path

from flightdeals import aircraft, evaluate, providers
from flightdeals.core import Offer, haversine_km

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
BUD = evaluate.load_budgets()
TODAY = date(2026, 11, 6)


def mk(dest, price, origin="CDG", days=(60, 75), **kw):
    return Offer(origin, dest, price, depart=TODAY + timedelta(days=days[0]),
                 return_date=TODAY + timedelta(days=days[1]), **kw)


class T(unittest.TestCase):
    def ev(self, o, hist=None):
        return evaluate.evaluate(o, CFG, hist or {}, BUD, TODAY)

    def test_haversine_paris_tokyo(self):
        self.assertAlmostEqual(haversine_km(49.013, 2.55, 35.55, 139.78), 9710, delta=60)

    def test_flight_cap_long(self):
        self.assertIsNotNone(self.ev(mk("BKK", 400, transfers=1)))
        self.assertIsNone(self.ev(mk("BKK", 650, transfers=1)))

    def test_total_cap_short_haul(self):
        # CDG-NYC ~5850 km: total cap 1000 €. 10 j à 105 €/j dépasse
        self.assertIsNone(self.ev(mk("NYC", 250, days=(30, 40))))
        # Marrakech: court + pas cher
        self.assertIsNotNone(self.ev(mk("RAK", 80, days=(30, 37))))

    def test_six_months_window(self):
        self.assertIsNone(self.ev(mk("BKK", 300, days=(250, 270), transfers=1)))

    def test_business(self):
        v = self.ev(mk("BOG", 760, origin="MAD", cabin="business"))
        self.assertEqual(v.kind, "business_deal")
        self.assertIsNone(self.ev(mk("BOG", 900, origin="MAD", cabin="business")))
        self.assertIsNone(self.ev(mk("RAK", 300, origin="MAD", cabin="business")))  # trop court

    def test_error_fare_by_history(self):
        hist = {"CDG-BKK-economy": [600, 650, 580, 620, 610, 640]}
        v = self.ev(mk("BKK", 250, transfers=1), hist)
        self.assertEqual(v.kind, "error_fare")
        self.assertGreaterEqual(v.discount_pct, 50)

    def test_narrowbody_only_route_rejected(self):
        # Route fictive servie uniquement en A320 : doit être rejetée au-delà de 5 h
        orig = aircraft._load_routes
        aircraft._load_routes = lambda p: {("CDG", "DXB"): {"320"}}
        try:
            st, _ = aircraft.check_route("CDG", ["DXB"], 0, 6.5, 5, "x")
            self.assertEqual(st, "REJECT")
        finally:
            aircraft._load_routes = orig

    def test_short_flight_no_constraint(self):
        st, _ = aircraft.check_route("CDG", ["RAK"], 0, 3.5, 5, "x")
        self.assertEqual(st, "not_required")

    def test_rss_parse(self):
        o = providers.parse_deal_title("ERROR FARE: Paris to Tokyo, Japan for only €329 roundtrip")
        self.assertEqual((o.origin, o.dest, o.price_eur, o.flagged_error), ("CDG", "TYO", 329.0, True))
        self.assertIsNone(providers.parse_deal_title("Paris to Tokyo for €300 one way"))
        b = providers.parse_deal_title("Business class: Madrid to Bogota from €699 roundtrip")
        self.assertEqual(b.cabin, "business")

    def test_tokyo_rejected_when_total_too_high(self):
        # vol bon marché mais séjour au Japon (70 €/j) -> au-dessus de 1400 € au total
        self.assertIsNone(self.ev(mk("TYO", 380)))

    def test_unknown_stay_uses_default(self):
        o = Offer("CDG", "RAK", 90, depart=TODAY + timedelta(days=30))
        self.assertEqual(self.ev(o).stay_days, 14)


if __name__ == "__main__":
    unittest.main()
