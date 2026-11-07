import copy
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flightdeals import evaluate, live, verify
from flightdeals.core import Offer

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
LOOSE = copy.deepcopy(CFG)
LOOSE["scoring"]["min_score"] = 0
LOOSE["scoring"]["require_anomaly"] = False
BUD = evaluate.load_budgets()
TODAY = date(2026, 11, 6)


def flight(num, airline, plane, cls="Economy"):
    return {"flight_number": num, "airline": airline, "airplane": plane, "travel_class": cls,
            "departure_airport": {"id": "CDG"}, "arrival_airport": {"id": "BKK"}}


def itinerary(price, *flights):
    return {"price": price, "flights": list(flights), "type": "Round trip", "total_duration": 700}


GOOD = {"best_flights": [itinerary(112, flight("AF 166", "Air France", "Boeing 777"))],
        "other_flights": [itinerary(140, flight("TG 931", "Thai Airways", "Airbus A350"))],
        "price_insights": {"lowest_price": 112, "price_level": "low", "typical_price_range": [480, 760]}}


class Parse(unittest.TestCase):
    def test_confirmed_with_aircraft_and_price_level(self):
        r = live.parse(GOOD, "AF", 109, 0.10)
        self.assertEqual(r.status, "confirmed")                       # 112 € vs 109 € annoncés : dans la tolérance de 10 %
        self.assertEqual((r.price, r.airlines, r.level, r.typical), (112.0, ["Air France"], "low", [480, 760]))
        self.assertEqual(r.aircraft, ["Boeing 777"])

    def test_price_went_up(self):
        r = live.parse(GOOD, "AF", 90, 0.10)                          # 112 € > 99 € maximum accepté
        self.assertEqual(r.status, "higher")
        self.assertIn("112", r.detail)

    def test_cheapest_of_the_announced_airline_is_used(self):
        data = {"best_flights": [itinerary(100, flight("TG 931", "Thai Airways", "Airbus A350"))],
                "other_flights": [itinerary(130, flight("AF 166", "Air France", "Boeing 777"))]}
        self.assertEqual(live.parse(data, "AF", 130, 0.10).price, 130.0)           # pas la moins chère d'une autre compagnie
        r = live.parse(data, "KL", 100, 0.10)                                       # compagnie annoncée absente chez Google
        self.assertEqual(r.price, 100.0)
        self.assertIn("n'apparaît pas", r.detail)

    def test_nothing_found_means_the_deal_is_gone(self):
        self.assertEqual(live.parse({"search_metadata": {}}, "AF", 100, 0.1).status, "gone")
        self.assertEqual(live.parse({"best_flights": [], "other_flights": []}, "AF", 100, 0.1).status, "gone")

    def test_api_error_is_unavailable_not_gone(self):
        r = live.parse({"error": "Invalid API key."}, "AF", 100, 0.1)
        self.assertEqual(r.status, "unavailable")
        self.assertIn("Invalid API key", r.detail)

    def test_malformed_options_are_ignored(self):
        data = {"best_flights": [{"price": "n/a", "flights": []}, {"flights": [flight("AF 1", "Air France", "A330")]}],
                "other_flights": [itinerary(120, flight("AF 166", "Air France", "Airbus A330"))]}
        self.assertEqual(live.parse(data, "AF", 120, 0.1).price, 120.0)

    def test_aircraft_verdict(self):
        self.assertEqual(live.aircraft_verdict(["Boeing 787", "Airbus A350"]), "widebody")
        self.assertEqual(live.aircraft_verdict(["Boeing 787", "Airbus A320"]), "narrowbody")
        self.assertEqual(live.aircraft_verdict([""]), "unknown")
        self.assertEqual(live.aircraft_verdict(["Fokker 70"]), "unknown")


class Budget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (live.USAGE, dict(os.environ))
        live.USAGE = Path(self.tmp.name) / "usage.json"

    def tearDown(self):
        live.USAGE = self.old[0]
        os.environ.clear()
        os.environ.update(self.old[1])
        self.tmp.cleanup()

    def test_no_key_no_live_check(self):
        os.environ.pop("SERPAPI_KEY", None)
        self.assertFalse(live.can_spend(CFG))

    def test_monthly_budget_is_enforced_and_resets(self):
        os.environ["SERPAPI_KEY"] = "k"
        cfg = copy.deepcopy(CFG)
        cfg["live"]["monthly_budget"] = 2
        now = datetime(2026, 11, 7, tzinfo=timezone.utc)
        self.assertTrue(live.can_spend(cfg, now))
        live._spend(now); live._spend(now)
        self.assertFalse(live.can_spend(cfg, now))                                  # quota du mois atteint
        self.assertTrue(live.can_spend(cfg, datetime(2026, 12, 1, tzinfo=timezone.utc)))   # nouveau mois : remis à zéro

    def test_a_search_spends_one_unit_even_on_failure(self):
        os.environ["SERPAPI_KEY"] = "k"
        old_get = live._get
        live._get = lambda p: (_ for _ in ()).throw(OSError("réseau"))
        try:
            r = live.check("CDG", "BKK", TODAY, TODAY + timedelta(days=14), "AF", 100, CFG)
        finally:
            live._get = old_get
        self.assertEqual(r.status, "unavailable")
        self.assertEqual(live.used(), 1)


class Confirm(unittest.TestCase):
    def v(self, dest="BKK", price=300, airline="AF"):
        o = Offer("CDG", dest, price, depart=TODAY + timedelta(days=60), return_date=TODAY + timedelta(days=76), transfers=0,
                  airline=airline, source="travelpayouts", link="https://x")
        return evaluate.evaluate(o, LOOSE, {}, BUD, TODAY)

    def fn(self, status, **kw):
        return lambda *a: live.Live(status, **kw)

    def test_confirmed_shows_live_price_aircraft_and_level(self):
        v = self.v()
        kept, dropped = verify.live_confirm([v], CFG, TODAY, 3, self.fn("confirmed", price=305.0, airlines=["Air France"],
                                            aircraft=["Boeing 777"], level="low", typical=[480, 760]))
        self.assertEqual((len(kept), len(dropped)), (1, 0))
        self.assertIn("EN DIRECT", v.verification)
        self.assertIn("305", v.verification)
        self.assertIn("niveau de prix bas", v.verification)
        self.assertEqual(v.aircraft, "widebody_confirmed")                          # l'avion est maintenant vérifié

    def test_price_up_or_gone_is_dropped(self):
        for st in ("higher", "gone"):
            kept, dropped = verify.live_confirm([self.v()], CFG, TODAY, 3, self.fn(st, detail="x"))
            self.assertEqual((len(kept), len(dropped)), (0, 1), st)

    def test_narrowbody_on_a_long_flight_is_dropped(self):
        kept, dropped = verify.live_confirm([self.v()], CFG, TODAY, 3, self.fn("confirmed", price=300.0, aircraft=["Airbus A321"]))
        self.assertEqual((len(kept), len(dropped)), (0, 1))

    def test_unavailable_keeps_the_offer_with_a_loud_warning(self):
        v = self.v()
        kept, dropped = verify.live_confirm([v], CFG, TODAY, 3, self.fn("unavailable", detail="quota"))
        self.assertEqual((len(kept), len(dropped)), (1, 0))
        self.assertIn("indisponible", v.verification)
        self.assertIn("avant d'acheter", v.verification)

    def test_no_key_keeps_but_warns(self):
        os.environ.pop("SERPAPI_KEY", None)
        v = self.v()
        kept, _ = verify.live_confirm([v], CFG, TODAY, 3)
        self.assertEqual(len(kept), 1)
        self.assertIn("NON confirmé en direct", v.verification)

    def test_spares_replace_the_dropped_and_the_limit_is_respected(self):
        vs = [self.v("BKK"), self.v("SGN"), self.v("DPS"), self.v("MNL")]
        answers = iter(["gone", "confirmed", "confirmed", "confirmed"])
        fn = lambda *a: live.Live(next(answers), price=300.0, aircraft=["Boeing 787"])
        kept, dropped = verify.live_confirm(vs, CFG, TODAY, 2, fn)
        self.assertEqual([v.dest_city for v in dropped], ["Bangkok"])
        self.assertEqual(len(kept), 2)                                              # le suivant prend la place
        self.assertEqual([v.dest_city for v in kept], ["Hô-Chi-Minh-Ville", "Bali"])  # le 4e n'est même pas interrogé (quota préservé)

    def test_rss_offer_is_not_searched_but_clearly_marked(self):
        v = self.v()
        v.offer.source = "rss:x"
        called = []
        kept, _ = verify.live_confirm([v], CFG, TODAY, 3, lambda *a: called.append(1))
        self.assertEqual((len(kept), called), (1, []))
        self.assertIn("Prix non confirmable", v.verification)


if __name__ == "__main__":
    unittest.main()
