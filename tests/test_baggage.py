import copy
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flightdeals import baggage, evaluate, links, notify, stopovers
from flightdeals.core import Leg, Offer

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
LOOSE = copy.deepcopy(CFG)
LOOSE["scoring"]["min_score"] = 0
LOOSE["scoring"]["require_anomaly"] = False
BUD = evaluate.load_budgets()
TODAY = date(2026, 11, 6)
ROUTES = str(ROOT / "data" / "routes.dat")


def offer(airline, price=300, dest="BKK", **kw):
    return Offer("CDG", dest, price, depart=TODAY + timedelta(days=60), return_date=TODAY + timedelta(days=76),
                 transfers=kw.pop("transfers", 1), airline=airline, link="https://aviasales.example/x", source="travelpayouts", **kw)


class Policy(unittest.TestCase):
    def test_full_service_includes_bags(self):
        b = baggage.assess("AF")
        self.assertEqual((b.supplement, b.status), (0, "inclus"))
        self.assertIn("sac à dos + bagage cabine inclus", b.note)

    def test_low_cost_charges_for_the_cabin_bag_both_ways(self):
        b = baggage.assess("FR")
        self.assertEqual((b.supplement, b.status), (60, "supplement"))          # 30 € x aller et retour
        self.assertEqual(baggage.assess("FR", directions=1).supplement, 30)      # un seul billet aller simple

    def test_unknown_airline_is_not_assumed_to_include_bags(self):
        b = baggage.assess("ZZ")
        self.assertEqual((b.supplement, b.status), (60, "inconnu"))
        self.assertEqual(baggage.assess("").status, "inconnu")

    def test_likely_is_flagged_but_not_charged(self):
        b = baggage.assess("TP")
        self.assertEqual((b.supplement, b.status), (0, "probable"))
        self.assertIn("confirme", b.note)

    def test_connections_warn_about_other_carriers(self):
        self.assertIn("autres compagnies", baggage.assess("AF", transfers=1).note)
        self.assertNotIn("autres compagnies", baggage.assess("AF", transfers=0).note)

    def test_worst_status_wins(self):
        self.assertEqual(baggage.worst(["inclus", "supplement", "probable"]), "supplement")
        self.assertEqual(baggage.worst(["inclus", "inclus"]), "inclus")

    def test_every_airline_row_is_complete(self):
        for code, row in json.loads((ROOT / "data" / "airlines.json").read_text()).items():
            if code.startswith("_"):
                continue
            self.assertIn(row["bag"], ("included", "likely", "fee"), code)
            self.assertTrue(row["site"].startswith("https://"), code)
            if row["bag"] == "fee":
                self.assertGreater(row["fee"], 0, code)


class InThePrice(unittest.TestCase):
    def ev(self, airline, **kw):
        return evaluate.evaluate(offer(airline, **kw), LOOSE, {}, BUD, TODAY)

    def test_supplement_is_added_to_the_flight_price_the_total_and_the_score(self):
        af, fr = self.ev("AF"), self.ev("FR")
        self.assertEqual(af.offer.price_eur, fr.offer.price_eur)                   # même tarif affiché par le moteur
        self.assertEqual(fr.flight_all_in - af.flight_all_in, 60)                  # mais pas le même prix RÉEL du vol
        self.assertEqual(fr.trip_total - af.trip_total, 60)                        # ni le même séjour complet
        self.assertLess(fr.score, af.score)                                        # ni la même note
        self.assertTrue(any("supplément bagages" in r for r in fr.reasons))

    def test_a_cheap_fare_on_a_low_cost_can_fall_below_the_threshold(self):
        score_fr = self.ev("FR").score
        cfg = copy.deepcopy(CFG)
        cfg["scoring"]["min_score"] = round(score_fr + 0.05, 1)                     # juste au-dessus de la note avec bagages
        cfg["scoring"]["require_anomaly"] = False
        self.assertIsNone(evaluate.evaluate(offer("FR"), cfg, {}, BUD, TODAY))
        self.assertIsNotNone(evaluate.evaluate(offer("AF"), cfg, {}, BUD, TODAY))   # le même tarif chez une compagnie qui les inclut passe

    def test_business_always_includes_bags(self):
        v = evaluate.evaluate_business(Offer("CDG", "TYO", 600, cabin="business", airline="FR"), CFG, BUD, TODAY)
        self.assertEqual((v.bag_status, v.bag_supplement), ("inclus", 0))
        self.assertIn("business", v.bag_note.lower())


class Links(unittest.TestCase):
    def test_google_flights_link_has_the_exact_dates(self):
        u = links.google_flights("CDG", "Bangkok", date(2027, 1, 19), date(2027, 1, 26))
        self.assertTrue(u.startswith("https://www.google.com/travel/flights?q="))
        self.assertIn("2027-01-19", u)
        self.assertIn("2027-01-26", u)
        self.assertIn("Bangkok", u)

    def test_official_airline_site_not_an_intermediary(self):
        self.assertEqual(links.airline_site("AF"), "https://www.airfrance.fr")
        self.assertEqual(links.airline_site("ZZ"), "")

    def test_verdict_carries_the_links(self):
        v = evaluate.evaluate(offer("AF"), LOOSE, {}, BUD, TODAY)
        self.assertEqual(v.links["airline_site"], "https://www.airfrance.fr")
        self.assertEqual(v.links["airline_name"], "Air France")
        self.assertIn("google.com/travel/flights", v.links["google_flights"])


class Alert(unittest.TestCase):
    def test_alert_text_shows_all_in_price_bags_and_how_to_check(self):
        v = evaluate.evaluate(offer("FR"), LOOSE, {}, BUD, TODAY)
        t = notify.body(v)
        self.assertIn("AVEC sac à dos + bagage cabine", t)
        self.assertIn("supplément bagages estimé 60", t)
        self.assertIn("🎒 Bagages", t)
        self.assertIn("AVANT D'ACHETER", t)
        self.assertIn("google.com/travel/flights", t)
        self.assertIn("SITE OFFICIEL", t)
        self.assertIn("cache d'un moteur de recherche", t)


class Combos(unittest.TestCase):
    def leg(self, o, d, hour, price, mins, airline, tz=0):
        t = TODAY + timedelta(days=40)
        when = datetime(t.year, t.month, t.day, hour, tzinfo=timezone(timedelta(hours=tz)))
        return Leg(o, d, when, mins, price, airline, f"https://x/{o}{d}")

    def test_each_separate_ticket_has_its_own_bag_policy(self):
        t = TODAY + timedelta(days=40)
        l1 = self.leg("CDG", "LIS", 8, 40, 150, "FR", 1)          # Ryanair : bagage cabine payant (30 €)
        l2 = self.leg("LIS", "BKK", 15, 190, 700, "AF")           # Air France : inclus
        ret = Leg("BKK", "CDG", datetime(t.year, t.month, t.day, 22, tzinfo=timezone(timedelta(hours=7))) + timedelta(days=20),
                  760, 220, "AF", "https://x/r")
        path = stopovers.Path([l1, l2], [("LIS", "short", 0)])
        v = stopovers.evaluate_combo(path, ret, 700, LOOSE, BUD, ROUTES, TODAY)
        self.assertIsNotNone(v)
        self.assertEqual(v.bag_supplement, 30)                                     # un seul des 3 billets est payant
        self.assertEqual(v.flight_all_in, 40 + 190 + 220 + 30)
        self.assertEqual(v.bag_status, "supplement")
        self.assertEqual(len(v.links["google_flights_legs"]), 3)                   # un lien de vérification par billet
        self.assertIn("https://www.airfrance.fr", v.links["airline_sites"])


if __name__ == "__main__":
    unittest.main()
