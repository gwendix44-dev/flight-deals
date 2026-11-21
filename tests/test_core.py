import unittest
from datetime import date, datetime, timedelta, timezone

from flightdeals import aircraft, baggage, combos, costs, evaluate as E, notify, prefs, scoring, slots, sources
from flightdeals.model import Offer
from flightdeals.util import tier, tier_index
from helpers import CFG, RAW, TODAY


def ev(dest="KGL", price=420, origin="CDG", out=40, stay=14, airline="KL", transfers=0, cabin="economy", cfg=CFG, flagged=False, hist=None):
    o = Offer(origin, dest, price, TODAY + timedelta(out), TODAY + timedelta(out + stay), transfers, airline, cabin, flagged_error=flagged)
    return E.evaluate(o, cfg, {"refused_keys": []}, hist or {}, TODAY)


class Rules(unittest.TestCase):
    def test_europe_not_a_destination(self):
        self.assertEqual(ev("LIS")[1], "destination inconnue")

    def test_north_africa_excluded(self):
        self.assertEqual(ev("TYO", cfg=prefs.effective(dict(RAW, excluded_countries=["JP"]), prefs.DEFAULT))[1], "pays exclu (Europe / Afrique du Nord / refus)")

    def test_notice_10_days(self):
        self.assertEqual(ev(out=5)[1], "départ dans moins de 10 jours")
        self.assertIsNotNone(ev(out=12)[0])

    def test_six_months(self):
        self.assertEqual(ev(out=250)[1], "départ au-delà de 6 mois")

    def test_min_stay_by_distance(self):
        self.assertEqual(ev("KGL", stay=5)[1], "séjour trop court pour la distance")  # ~6 400 km -> 7 j
        self.assertEqual(ev("SYD", stay=12)[1], "séjour trop court pour la distance")  # >10 000 km -> 14 j

    def test_max_stay_three_weeks(self):
        self.assertEqual(ev(stay=22)[1], "séjour au-delà de 3 semaines")

    def test_transfers_max_two(self):
        self.assertEqual(ev(transfers=3)[1], "trop d'escales")
        self.assertIsNotNone(ev(transfers=2)[0])

    def test_implausible_price(self):
        self.assertEqual(ev(price=40)[1], "prix aberrant (donnée douteuse)")
        self.assertIsNotNone(ev(price=40, flagged=True)[0])

    def test_budget_total_includes_stay(self):
        d, why = ev("TYO", price=420, stay=14)
        self.assertIn(why, ("budget total dépassé",)) if why else self.assertLessEqual(d["total"], d["cap"])

    def test_us_stay_never_fits_1500(self):
        self.assertEqual(ev("NYC", price=300, stay=14)[1], "budget total dépassé")

    def test_positioning_added_to_stay_not_flight(self):
        d, _ = ev("KGL", origin="LIS", price=300)
        if d:
            self.assertEqual(d["positioning"], 125)
            self.assertEqual(d["flight_price"], 300)

    def test_business_cap_and_min_distance(self):
        self.assertEqual(ev("BOG", price=900, cabin="business")[1], "business : au-dessus du plafond")
        self.assertEqual(ev("TLV", price=400, cabin="business", stay=7)[1], "business : distance trop courte")
        self.assertIsNotNone(ev("DXB", price=700, cabin="business", stay=7)[0])

    def test_business_score_formula(self):
        s = scoring.score_business(price=1200, km=8000, flagged_error=False, cfg=CFG)
        bench = 3.2 * (150 + 0.08 * 8000)
        self.assertAlmostEqual(s["score"], round(11 * (1 - 1200 / bench) / 0.85, 1), 1)


class Scoring(unittest.TestCase):
    def test_max_is_11(self):
        d, _ = ev("SAL", price=100, flagged=True, airline="TP")
        self.assertLessEqual(d["score"], 11)

    def test_error_bonus(self):
        a, _ = ev("ALA", price=300)
        b, _ = ev("ALA", price=300, flagged=True)
        self.assertGreater(b["score"], a["score"])

    def test_history_median_bonus(self):
        hist = {"CDG-KGL": [[20261101 + i, 800] for i in range(6)]}
        a, _ = ev("KGL", price=380, hist=hist)
        b, _ = ev("KGL", price=380)
        self.assertGreaterEqual(a["score"], b["score"])


class Baggage(unittest.TestCase):
    def test_fee_airline_surcharge_both_ways(self):
        b = baggage.baggage_for("FR", CFG)
        self.assertEqual(b["surcharge"], 60)
        self.assertEqual(b["status"], "fee")

    def test_unknown_airline_60(self):
        self.assertEqual(baggage.baggage_for("ZZ", CFG)["surcharge"], 60)

    def test_included_zero(self):
        self.assertEqual(baggage.baggage_for("AF", CFG)["surcharge"], 0)

    def test_business_included(self):
        self.assertEqual(baggage.baggage_for("FR", CFG, "business")["surcharge"], 0)

    def test_surcharge_added_before_score(self):
        a, _ = ev("KGL", price=380, airline="KL")
        b, _ = ev("KGL", price=380, airline="FR")
        self.assertEqual(b["flight_price"], a["flight_price"] + 60)


class Aircraft(unittest.TestCase):
    def test_short_flight_no_requirement(self):
        self.assertEqual(aircraft.check("CDG", ["BCN"], 1000, 0, CFG)[0], "not_required")

    def test_long_with_transfer_unverified(self):
        self.assertEqual(aircraft.check("CDG", ["BKK"], 9500, 1, CFG)[0], "unverified")

    def test_strict_mode_rejects_unverified(self):
        cfg = prefs.effective(RAW, dict(prefs.DEFAULT, strict_aircraft=True))
        o = Offer("CDG", "KGL", 400, TODAY + timedelta(40), TODAY + timedelta(54), 1, "KL")
        self.assertEqual(E.evaluate(o, cfg, {"refused_keys": []}, {}, TODAY)[1], "mode avion strict : gros-porteur non confirmé")


class Costs(unittest.TestCase):
    def test_thailand_cheap_us_expensive(self):
        d = date(2027, 3, 1)
        th = costs.stay_cost("TH", d, d + timedelta(14), CFG)
        us = costs.stay_cost("US", d, d + timedelta(14), CFG)
        self.assertLess(th["per_day"], 45)
        self.assertGreater(us["total"], 1500)

    def test_peak_season_costs_more(self):
        a = costs.stay_cost("TH", date(2027, 3, 1), date(2027, 3, 15), CFG)["total"]
        b = costs.stay_cost("TH", date(2026, 12, 22), date(2027, 1, 5), CFG)["total"]
        self.assertGreater(b, a)


class Slots(unittest.TestCase):
    def test_noon_paris_in_winter_is_11_utc(self):
        due = slots.due_slot(datetime(2026, 11, 21, 11, 5, tzinfo=timezone.utc), {}, CFG)
        self.assertEqual(due[0], "2026-11-21@12:00")

    def test_summer_time_handled(self):
        due = slots.due_slot(datetime(2027, 7, 1, 10, 5, tzinfo=timezone.utc), {}, CFG)
        self.assertEqual(due[0], "2027-07-01@12:00")

    def test_catch_up_within_3h_only_once(self):
        t = datetime(2026, 11, 21, 13, 30, tzinfo=timezone.utc)
        self.assertIsNotNone(slots.due_slot(t, {}, CFG))
        self.assertIsNone(slots.due_slot(t, {"2026-11-21@12:00": "x"}, CFG))
        self.assertIsNone(slots.due_slot(datetime(2026, 11, 21, 14, 30, tzinfo=timezone.utc), {}, CFG))


class Sources(unittest.TestCase):
    def test_rss_parse_error_fare(self):
        o = sources.parse_deal_title("Paris to Kathmandu for €300 return - error fare", "x")
        self.assertTrue(o.flagged_error)
        self.assertEqual((o.origin, o.dest, o.price), ("CDG", "KTM", 300))

    def test_rss_one_way_ignored(self):
        self.assertIsNone(sources.parse_deal_title("Paris to Bangkok one way €200", "x"))

    def test_rss_broken_xml_tolerated(self):
        raw = "<rss><item><title>Paris to Lima for €400 return</title><link>u</link></item><item><title>oops &</title>"
        self.assertEqual(len(sources.rss_items(raw)), 1)


class Combos(unittest.TestCase):
    def test_no_airport_night(self):
        arr = datetime(2026, 12, 1, 22, 0, tzinfo=timezone.utc)
        self.assertIsNone(combos.layover_ok(arr, arr + timedelta(hours=7), 0, CFG))  # 22h -> 5h : nuit
        self.assertEqual(combos.layover_ok(arr.replace(hour=8), arr.replace(hour=8) + timedelta(hours=6), 0, CFG), "short")
        self.assertEqual(combos.layover_ok(arr, arr + timedelta(hours=45), 0, CFG), "long")
        self.assertIsNone(combos.layover_ok(arr, arr + timedelta(hours=2), 0, CFG))


class Notify(unittest.TestCase):
    def test_empty_slot_message(self):
        t, _ = notify.slot_message("Publication de 12h", [], [])
        self.assertIn("rien d'exceptionnel", t)

    def test_no_config_returns_false(self):
        import os
        os.environ.pop("VAPID_PRIVATE_KEY", None)
        self.assertFalse(notify.send_push("a", "b"))


class Prefs(unittest.TestCase):
    def test_prefs_only_harden(self):
        p = dict(prefs.DEFAULT, cap_by_tier={"0": 3000}, max_transfers=5)
        c = prefs.effective(RAW, p)
        self.assertEqual(c["budget_by_distance_km"][0][1], 1500)  # un plafond plus haut ne relâche rien
        self.assertEqual(c["max_transfers"], 2)


if __name__ == "__main__":
    unittest.main()
