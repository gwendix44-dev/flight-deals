import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flightdeals import evaluate, stopovers
from flightdeals.core import Leg

ROOT = Path(__file__).resolve().parent.parent
import copy
CFG = json.loads((ROOT / "config.json").read_text())
LOOSE = copy.deepcopy(CFG)
LOOSE["scoring"]["min_score"] = 0
BUD = evaluate.load_budgets()
ROUTES = str(ROOT / "data" / "routes.dat")
TODAY = date(2026, 11, 6)
U = timezone.utc


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=U)


class Layover(unittest.TestCase):
    def test_rules(self):
        arr = utc(2026, 12, 1, 10)                       # arrivée 10h, hub UTC+0
        self.assertEqual(stopovers.classify_layover(arr, 0, utc(2026, 12, 1, 16))[0], "short")   # 6 h de jour
        self.assertIsNone(stopovers.classify_layover(arr, 0, utc(2026, 12, 1, 12)))              # 2 h : trop court
        self.assertIsNone(stopovers.classify_layover(arr, 0, utc(2026, 12, 1, 23)))              # 13 h
        self.assertIsNone(stopovers.classify_layover(utc(2026, 12, 1, 20), 0, utc(2026, 12, 2, 6)))  # 10 h de nuit
        self.assertIsNone(stopovers.classify_layover(arr, 0, utc(2026, 12, 2, 10)))              # 24 h, 1 nuit
        k, n = stopovers.classify_layover(arr, 0, utc(2026, 12, 3, 12))                          # 2 nuits
        self.assertEqual((k, n), ("stopover", 2))

    def test_timezone_matters(self):
        # arrivée 21:00 UTC = 00:00 heure locale (UTC+3) ; départ 05:30 UTC+3 -> nuit à l'aéroport
        dep = datetime(2026, 12, 2, 5, 30, tzinfo=timezone(timedelta(hours=3)))
        self.assertIsNone(stopovers.classify_layover(utc(2026, 12, 1, 21), 3, dep))


def leg(o, d, when, price, mins, tz=0):
    return Leg(o, d, when.replace(tzinfo=timezone(timedelta(hours=tz))), mins, price, "XX", f"https://x/{o}{d}")


class Build(unittest.TestCase):
    def setUp(self):
        t = TODAY + timedelta(days=40)
        d0 = datetime(t.year, t.month, t.day)
        self.d0 = d0
        l1 = leg("CDG", "LIS", d0.replace(hour=8), 40, 150, tz=1)          # arrive 09:30 UTC
        l2 = leg("LIS", "BKK", d0.replace(hour=15), 190, 700, tz=0)        # 5,5 h d'escale
        l2b = leg("LIS", "IST", d0.replace(hour=15), 30, 240, tz=0)        # arrive 19:00 UTC = 22:00 Istanbul
        l3 = leg("IST", "BKK", d0 + timedelta(days=3, hours=10), 150, 600, tz=3)   # 2+ nuits à Istanbul
        self.legs_from = {"CDG": {"LIS": [l1]}, "LIS": {"BKK": [l2], "IST": [l2b]}, "IST": {"BKK": [l3]}}
        self.l1, self.l2, self.l3, self.l2b = l1, l2, l3, l2b

    def test_paths(self):
        paths = [p for p in stopovers.build_paths(self.legs_from, 600) if p.legs[0].orig == "CDG"]
        self.assertEqual(sorted(len(p.legs) for p in paths), [2, 3])
        three = next(p for p in paths if len(p.legs) == 3)
        self.assertEqual([k for _, k, _ in three.layovers], ["short", "stopover"])

    def test_never_more_than_two_stops(self):
        # un 4e tronçon n'est jamais construit
        for p in stopovers.build_paths(self.legs_from, 600):
            self.assertLessEqual(len(p.legs), 3)

    def ret(self, price=220, days=20):
        a = self.d0 + timedelta(days=days)
        return leg("BKK", "CDG", a.replace(hour=22), price, 760, tz=7)

    def test_combo_ok_and_filters(self):
        path = stopovers.Path([self.l1, self.l2], [("LIS", "short", 0)])
        ev = lambda ret, base: stopovers.evaluate_combo(path, ret, base, LOOSE, BUD, ROUTES, TODAY)
        v = ev(self.ret(), 700)
        self.assertIsNotNone(v)
        self.assertEqual(v.kind, "stopover_deal")
        self.assertGreaterEqual(v.saving_pct, 20)
        self.assertEqual(v.offer.price_eur, 450)
        self.assertGreater(v.score, 0)
        self.assertIsNone(ev(self.ret(), 520))                  # gain < 20 %
        self.assertIsNone(ev(self.ret(), None))                 # pas de prix de référence
        self.assertIsNone(ev(self.ret(days=2), 700))            # séjour trop court pour 9 400 km
        self.assertIsNone(ev(self.ret(days=30), 700))           # plus de 3 semaines
        self.assertIsNone(ev(self.ret(price=1200), 2500))       # > 1500 € tout compris

    def test_strict_grid_applies_to_combos(self):
        path = stopovers.Path([self.l1, self.l2], [("LIS", "short", 0)])
        # Bangkok est une destination grand public et 2 billets séparés : sous 9,5/11
        self.assertIsNone(stopovers.evaluate_combo(path, self.ret(), 700, CFG, BUD, ROUTES, TODAY))

    def test_stopover_cost_counted(self):
        path = stopovers.Path([self.l1, self.l2b, self.l3], [("LIS", "short", 0), ("IST", "stopover", 2)])
        v = stopovers.evaluate_combo(path, self.ret(days=20), 700, LOOSE, BUD, ROUTES, TODAY)
        self.assertIsNotNone(v)
        self.assertTrue(any("mini-étape" in x for x in v.itinerary))
        self.assertGreater(v.stay_cost, 600)


if __name__ == "__main__":
    unittest.main()
