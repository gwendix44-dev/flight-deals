import copy
import json
import unittest
from datetime import date, timedelta
from pathlib import Path

from flightdeals import aircraft, costs, evaluate, preferences, providers, scoring, verify
from flightdeals.core import Offer, haversine_km

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
LOOSE = copy.deepcopy(CFG)
LOOSE["scoring"]["require_anomaly"] = False
LOOSE["scoring"]["min_score"] = 0          # teste les règles dures indépendamment de la note
BUD = evaluate.load_budgets()
TODAY = date(2026, 11, 6)


def mk(dest, price, origin="CDG", days=(60, 75), **kw):
    return Offer(origin, dest, price, depart=TODAY + timedelta(days=days[0]),
                 return_date=TODAY + timedelta(days=days[1]), **kw)


class Rules(unittest.TestCase):
    def ev(self, o, hist=None, cfg=LOOSE):
        return evaluate.evaluate(o, cfg, hist or {}, BUD, TODAY)

    def test_haversine_paris_tokyo(self):
        self.assertAlmostEqual(haversine_km(49.013, 2.55, 35.55, 139.78), 9710, delta=60)

    def test_cap_grows_with_distance(self):
        self.assertEqual([scoring.total_cap(k, CFG) for k in (5000, 9000, 16000)], [1500, 1900, 2500])
        self.assertIsNotNone(self.ev(mk("SYD", 600, days=(60, 74), transfers=1)))     # Sydney : possible avec un très bon vol
        self.assertIsNone(self.ev(mk("SYD", 1000, days=(60, 74), transfers=1)))       # mais pas à 1 000 € de vol

    def test_total_budget_1500(self):
        self.assertIsNotNone(self.ev(mk("BKK", 300, days=(60, 74), transfers=1)))    # ~1100 € tout compris
        self.assertIsNone(self.ev(mk("TYO", 700, days=(60, 75), transfers=1)))       # Japon : > 1500 € au total

    def test_min_stay_grows_with_distance(self):
        for km, d in ((3000, 5), (5000, 7), (8000, 10), (12000, 14)):
            self.assertEqual(scoring.min_stay_for(km, CFG), d)

    def test_stay_window(self):
        self.assertIsNone(self.ev(mk("BKK", 300, days=(60, 66), transfers=1)))       # 6 j : trop court pour 9 400 km
        self.assertIsNone(self.ev(mk("BKK", 300, days=(60, 85), transfers=1)))       # 25 j : > 3 semaines
        self.assertIsNotNone(self.ev(mk("BKK", 300, days=(60, 72), transfers=1)))    # 12 j : ok
        self.assertIsNotNone(self.ev(mk("TLV", 200, days=(60, 65))))                 # 5 j suffisent à 3 300 km
        self.assertIsNone(self.ev(mk("TLV", 200, days=(60, 64))))                    # mais pas 4

    def test_six_months_window(self):
        self.assertIsNone(self.ev(mk("BKK", 300, days=(250, 264), transfers=1)))

    def test_error_fare_by_history(self):
        hist = {"CDG-BKK-economy": [600, 650, 580, 620, 610, 640]}
        v = self.ev(mk("BKK", 250, days=(60, 72), transfers=1), hist)
        self.assertEqual(v.kind, "error_fare")

    def test_max_two_transfers(self):
        self.assertIsNotNone(self.ev(mk("BKK", 300, days=(60, 72), transfers=2)))
        self.assertIsNone(self.ev(mk("BKK", 300, days=(60, 72), transfers=3)))

    def test_north_africa_excluded(self):
        for d in ("RAK", "CMN", "TUN", "CAI", "HRG"):
            self.assertIsNone(self.ev(mk(d, 60, days=(30, 37))), d)

    def test_narrowbody_only_route_rejected(self):
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

    def test_unknown_dates_use_distance_based_stay(self):
        o = Offer("CDG", "ACC", 90, depart=TODAY + timedelta(days=30))
        self.assertEqual(self.ev(o).stay_days, scoring.default_stay(5000, CFG))

    def test_rss_parse(self):
        o = providers.parse_deal_title("ERROR FARE: Paris to Tokyo, Japan for only €329 roundtrip")
        self.assertEqual((o.origin, o.dest, o.price_eur, o.flagged_error), ("CDG", "TYO", 329.0, True))
        self.assertIsNone(providers.parse_deal_title("Paris to Tokyo for €300 one way"))
        b = providers.parse_deal_title("Business class: Madrid to Bogota from €699 roundtrip")
        self.assertEqual(b.cabin, "business")

    def test_rss_tolerates_broken_xml(self):
        raw = '<rss><channel><item><title><![CDATA[Paris to Bali for €399 roundtrip]]></title><link>https://x/1</link>' \
              '<description>a & b <br></description></item></channel>'
        self.assertEqual(providers._rss_items(raw), [("Paris to Bali for €399 roundtrip", "https://x/1")])


class Grid(unittest.TestCase):
    def test_max_is_11(self):
        s = scoring.score_deal(price=50, km=9000, cabin="economy", total=500, stay=12, stops=0,
                               aircraft_status="widebody_probable", secrecy=1.5, separate_tickets=False,
                               cfg=CFG, flagged_error=True)
        self.assertEqual(s.total, 11.0)

    def test_mundane_deal_rejected_by_strict_grid(self):
        o = mk("BKK", 400, days=(60, 72), transfers=1)
        self.assertIsNone(evaluate.evaluate(o, CFG, {}, BUD, TODAY))

    def test_exceptional_offbeat_error_fare_accepted(self):
        o = mk("ALA", 200, days=(60, 69), flagged_error=True)       # Almaty direct, erreur de prix signalée
        v = evaluate.evaluate(o, CFG, {}, BUD, TODAY)
        self.assertIsNotNone(v)
        self.assertGreaterEqual(v.score, 9.5)
        self.assertEqual(v.kind, "error_fare")

    def test_secret_destination_scores_higher_than_mainstream(self):
        kw = dict(price=250, km=7000, cabin="economy", total=700, stay=10, stops=1, aircraft_status="unverified",
                  separate_tickets=False, cfg=CFG)
        self.assertGreater(scoring.score_deal(secrecy=1.5, **kw).total, scoring.score_deal(secrecy=0.0, **kw).total)

    def test_budget_points_fall_to_zero_at_cap(self):
        kw = dict(price=300, km=7000, cabin="economy", stay=10, stops=0, aircraft_status="unverified",
                  secrecy=1, separate_tickets=False, cfg=CFG)
        self.assertEqual(scoring.score_deal(total=1500, **kw).parts["budget"], 0)
        self.assertEqual(scoring.score_deal(total=800, **kw).parts["budget"], 2)


DEAL = {"offer": {"dest": "BKK", "transfers": 1, "depart": "2026-12-20"}, "dest_city": "Bangkok", "country": "TH",
        "trip_total": 1300, "stay_days": 12, "distance_km": 9448, "flight_hours": 14.4}


class Feedback(unittest.TestCase):
    def learn(self, text, prefs=None, deal=DEAL):
        return preferences.learn(prefs or preferences.load_prefs(Path("/nonexistent")), text, deal, CFG)

    def test_too_expensive_lowers_budget_below_refused_deal(self):
        p, msgs = self.learn("Trop cher pour ce que c'est")
        self.assertEqual(p["cap_by_tier"], {"1": 1150})        # palier 8 000-12 000 km : 1300 × 0,9 arrondi à 50
        self.assertTrue(msgs)

    def test_explicit_budget(self):
        p, _ = self.learn("trop cher, max 1100 €")
        self.assertEqual(p["total_cap_eur"], 1100)

    def test_too_short_increases_minimum_stay(self):
        p, _ = self.learn("séjour trop court")
        self.assertEqual(p["min_stay_extra"], 2)
        cfg = preferences.apply_prefs(CFG, p)
        self.assertEqual(scoring.min_stay_for(9448, cfg), 12)       # 10 j de base + 2

    def test_explicit_days(self):
        p, _ = self.learn("trop court, je veux au moins 14 jours")
        self.assertEqual(scoring.min_stay_for(9448, preferences.apply_prefs(CFG, p)), 14)

    def test_flight_too_long_vs_stay_too_long(self):
        p, _ = self.learn("le vol est trop long")
        self.assertEqual(p["max_flight_hours"], 12.9)
        self.assertIsNone(p["max_stay_days"])
        p, _ = self.learn("séjour trop long")
        self.assertEqual(p["max_stay_days"], 10)

    def test_escales_destination_plane_and_separate_tickets(self):
        self.assertEqual(self.learn("trop d'escales")[0]["max_transfers"], 0)
        self.assertEqual(self.learn("destination déjà vue")[0]["excluded_destinations"], ["BKK"])
        self.assertEqual(self.learn("je ne veux plus de ce pays")[0]["excluded_countries"], ["TH"])
        self.assertTrue(self.learn("avion pas adapté, monocouloir")[0]["strict_aircraft"])
        self.assertTrue(self.learn("trop risqué ces billets séparés")[0]["stopovers_disabled"])
        self.assertEqual(self.learn("mauvaise période")[0]["excluded_months"], [12])

    def test_unknown_reason_changes_nothing(self):
        p, msgs = self.learn("bof je sais pas trop")
        self.assertEqual(msgs[0].startswith("Exigence"), True)       # « bof » = pas assez exceptionnel
        p, msgs = self.learn("hmm non merci")
        self.assertEqual(msgs, [])

    def test_learned_preferences_filter_offers(self):
        p, _ = self.learn("destination déjà vue")
        cfg = preferences.apply_prefs(LOOSE, p)
        self.assertIsNone(evaluate.evaluate(mk("BKK", 300, days=(60, 72), transfers=1), cfg, {}, BUD, TODAY))
        self.assertIsNotNone(evaluate.evaluate(mk("SGN", 300, days=(60, 75), transfers=1), cfg, {}, BUD, TODAY))
        p, _ = self.learn("trop cher, max 900 €")
        cfg = preferences.apply_prefs(LOOSE, p)
        self.assertIsNone(evaluate.evaluate(mk("BKK", 500, days=(60, 72), transfers=1), cfg, {}, BUD, TODAY))

    def test_stricter_threshold_and_never_loosens_config(self):
        p, _ = self.learn("pas assez exceptionnel")
        self.assertEqual(preferences.apply_prefs(CFG, p)["scoring"]["min_score"], round(CFG["scoring"]["min_score"] + 0.3, 1))
        p = preferences.load_prefs(Path("/nonexistent")); p["total_cap_eur"] = 5000
        self.assertEqual(preferences.apply_prefs(CFG, p)["economy"]["total_trip_cap_eur"][0][1], 1500)


class Diversity(unittest.TestCase):
    def test_no_single_region_takes_everything(self):
        from flightdeals import main
        cfg = copy.deepcopy(LOOSE)
        vs = []
        for dest, org in (("BKK", "CDG"), ("HKT", "CDG"), ("SGN", "CDG"), ("DPS", "MAD"), ("BOG", "CDG"), ("LIM", "CDG")):
            v = evaluate.evaluate(mk(dest, 200, origin=org, days=(60, 75), transfers=1), cfg, {}, BUD, TODAY)
            if v:
                vs.append(v)
        top = main.dispatch(vs, {}, cfg, True, 5)
        asia = [v for v in top if v.country in {"TH", "VN", "ID"}]
        self.assertLessEqual(len(asia), 2)
        self.assertEqual(len({v.offer.dest for v in top}), len(top))     # pas deux fois la même destination


class Realism(unittest.TestCase):
    def test_cost_breakdown_covers_all_posts(self):
        total, lines = costs.stay_breakdown(BUD, "TH", 14, date(2027, 2, 10), CFG)
        labels = " ".join(l for l, _ in lines)
        for word in ("Hébergement", "Nourriture", "Transports", "Activités", "Déplacements", "Assurance", "Transferts", "Marge"):
            self.assertIn(word, labels)
        self.assertAlmostEqual(total, sum(v for _, v in lines), delta=6)          # arrondis près

    def test_expensive_countries_cost_more_than_asia(self):
        us = costs.stay_breakdown(BUD, "US", 10, date(2027, 2, 10), CFG)[0]
        th = costs.stay_breakdown(BUD, "TH", 10, date(2027, 2, 10), CFG)[0]
        self.assertGreater(us, 2 * th)

    def test_peak_season_raises_lodging(self):
        normal = costs.stay_breakdown(BUD, "TH", 10, date(2027, 3, 10), CFG)[0]
        peak = costs.stay_breakdown(BUD, "TH", 10, date(2026, 12, 24), CFG)[0]
        self.assertGreater(peak, normal)

    def test_visa_is_included(self):
        lines = dict(costs.stay_breakdown(BUD, "IN", 14, date(2027, 2, 10), CFG)[1])
        self.assertTrue(any("Visa" in k for k in lines))

    def test_departure_too_soon_rejected(self):
        self.assertIsNone(evaluate.evaluate(mk("BKK", 300, days=(5, 19), transfers=1), LOOSE, {}, BUD, TODAY))

    def test_implausible_price_rejected(self):
        self.assertIsNone(evaluate.evaluate(mk("BKK", 20, days=(60, 72), transfers=1), LOOSE, {}, BUD, TODAY))


class Verification(unittest.TestCase):
    def verdict(self, **kw):
        return evaluate.evaluate(mk("BKK", 300, days=(60, 72), transfers=1, **kw), LOOSE, {}, BUD, TODAY)

    def test_confirmed(self):
        v = self.verdict()
        ok, msg = verify.verify_one(v, CFG, "t", TODAY, price_fn=lambda *a: 310.0)     # +3 % : toléré
        self.assertTrue(ok)
        self.assertIn("Revérifié", msg)

    def test_price_went_up_or_vanished_or_api_down(self):
        v = self.verdict()
        self.assertFalse(verify.verify_one(v, CFG, "t", TODAY, price_fn=lambda *a: 400.0)[0])
        self.assertFalse(verify.verify_one(v, CFG, "t", TODAY, price_fn=lambda *a: None)[0])
        def boom(*a): raise OSError("réseau")
        ok, msg = verify.verify_one(v, CFG, "t", TODAY, price_fn=boom)
        self.assertFalse(ok)
        self.assertIn("impossible", msg)

    def test_nothing_shown_without_token(self):
        v = self.verdict()
        self.assertEqual(verify.verify_all([v], CFG, None, TODAY), [])

    def test_only_verified_offers_are_kept(self):
        a, b = self.verdict(), evaluate.evaluate(mk("SGN", 300, days=(60, 75), transfers=1), LOOSE, {}, BUD, TODAY)
        prices = {"BKK": 300.0, "SGN": None}
        kept = verify.verify_all([a, b], CFG, "t", TODAY, price_fn=lambda o, d, *r: prices[d])
        self.assertEqual([v.offer.dest for v in kept], ["BKK"])
        self.assertTrue(kept[0].verification)

    def test_rss_flagged_as_to_confirm(self):
        o = providers.parse_deal_title("ERROR FARE: Paris to Bali for €299 roundtrip")
        v = evaluate.evaluate(o, LOOSE, {}, BUD, TODAY)
        ok, msg = verify.verify_one(v, CFG, "t", TODAY, price_fn=lambda *a: 1 / 0)
        self.assertTrue(ok)
        self.assertIn("NON revérifiables", msg)


class WholePlanet(unittest.TestCase):
    def test_round_robin_across_regions(self):
        from flightdeals import main
        cfg = copy.deepcopy(LOOSE)
        vs = []
        for dest, org, d in (("BKK", "CDG", (60, 72)), ("HKT", "CDG", (60, 72)), ("SGN", "CDG", (60, 75)),
                             ("DPS", "MAD", (60, 75)), ("BOG", "CDG", (60, 72)), ("LIM", "CDG", (60, 75)),
                             ("DKR", "CDG", (60, 68)), ("NYC", "AMS", (60, 68))):
            v = evaluate.evaluate(mk(dest, 250, origin=org, days=d, transfers=1), cfg, {}, BUD, TODAY)
            if v:
                vs.append(v)
        from flightdeals.airports import region_of
        top = main.dispatch(vs, {}, cfg, True, 5)
        regions = {region_of(v.country) for v in top}
        self.assertGreaterEqual(len(regions), 3)                       # pas seulement l'Asie
        self.assertLessEqual(sum(region_of(v.country) == "asie" for v in top), 2)

    def test_many_destinations_on_every_continent(self):
        from flightdeals.airports import DESTINATIONS, REGIONS, region_of
        self.assertGreaterEqual(len(DESTINATIONS), 150)
        for reg in REGIONS:
            self.assertGreaterEqual(sum(region_of(v[1]) == reg for v in DESTINATIONS.values()), 4, reg)
        self.assertTrue(all(v[1] in BUD or v[1] in CFG["excluded_countries"] for v in DESTINATIONS.values()))   # chaque pays autorisé a un barème


class Home(unittest.TestCase):
    def test_home_airports_have_no_positioning_cost(self):
        for o in ("NTE", "CDG", "ORY"):
            self.assertIsNone(costs.positioning(o, CFG))

    def test_other_airports_add_the_cheapest_ticket_from_home(self):
        amt, label = costs.positioning("LIS", CFG)
        self.assertEqual(amt, 120)                       # Paris -> Lisbonne, moins cher que depuis Nantes (130)
        self.assertIn("Paris", label)
        self.assertEqual(costs.positioning("DUB", CFG)[0], 110)

    def test_positioning_in_stay_not_in_flight_price(self):
        cdg = evaluate.evaluate(mk("BKK", 300, origin="CDG", days=(60, 76), transfers=1), LOOSE, {}, BUD, TODAY)
        lis = evaluate.evaluate(mk("BKK", 300, origin="LIS", days=(60, 76), transfers=1), LOOSE, {}, BUD, TODAY)
        self.assertEqual(cdg.offer.price_eur, lis.offer.price_eur)                 # le prix du vol ne change pas
        self.assertGreater(lis.stay_cost, cdg.stay_cost)                           # le séjour, si
        self.assertTrue(any("Trajet A/R" in lab for lab, _ in lis.cost_lines))
        self.assertFalse(any("Trajet A/R" in lab for lab, _ in cdg.cost_lines))
        self.assertGreaterEqual(lis.trip_total - cdg.trip_total, 110)

    def test_positioning_can_make_an_offer_unaffordable(self):
        # sans le trajet l'offre tient dans le budget, avec elle non
        cfg = copy.deepcopy(LOOSE)
        cfg["economy"]["total_trip_cap_eur"] = [[8000, 1500], [12000, 1000], [1000000, 2500]]
        base = evaluate.evaluate(mk("BKK", 400, origin="CDG", days=(60, 72), transfers=1), cfg, {}, BUD, TODAY)
        self.assertIsNotNone(base)
        cfg["economy"]["total_trip_cap_eur"][1][1] = base.trip_total + 60               # marge < trajet de 120 €
        self.assertIsNotNone(evaluate.evaluate(mk("BKK", 400, origin="CDG", days=(60, 72), transfers=1), cfg, {}, BUD, TODAY))
        self.assertIsNone(evaluate.evaluate(mk("BKK", 400, origin="LIS", days=(60, 72), transfers=1), cfg, {}, BUD, TODAY))


class Business(unittest.TestCase):
    def biz(self, dest, price, origin="CDG", **kw):
        o = Offer(origin, dest, price, cabin="business", **kw)
        return evaluate.evaluate_business(o, CFG, BUD, TODAY)

    def test_good_business_deal_ignores_stay_price(self):
        v = self.biz("TYO", 780)                    # Japon : séjour cher, sans importance ici
        self.assertEqual(v.kind, "business_deal")
        self.assertEqual(v.score, 0)                # pas de note sur 11 : section à part
        self.assertTrue(v.stay_cost > 600)          # affiché à titre indicatif

    def test_cap_800_long_haul_and_real_discount(self):
        self.assertIsNone(self.biz("TYO", 850))                       # au-dessus de 800 €
        self.assertIsNone(self.biz("DKR", 700, origin="MAD"))        # court-courrier (3 000 km)
        self.assertIsNone(self.biz("TYO", 100))                       # prix irréaliste
        self.assertIsNotNone(self.biz("TYO", 100, flagged_error=True))   # sauf erreur de prix signalée

    def test_minimum_discount_is_enforced(self):
        self.assertIsNotNone(self.biz("ACC", 800))                       # ~ -53 % vs prix habituel du business
        cfg = copy.deepcopy(CFG)
        cfg["business"]["min_discount"] = 0.6
        o = Offer("CDG", "ACC", 800, cabin="business")
        self.assertIsNone(evaluate.evaluate_business(o, cfg, BUD, TODAY))   # trop peu de remise pour être « très bon »

    def test_business_and_economy_are_separate_flows(self):
        o = Offer("CDG", "TYO", 500, cabin="business", depart=TODAY + timedelta(days=60),
                  return_date=TODAY + timedelta(days=75))
        self.assertIsNone(evaluate.evaluate(o, LOOSE, {}, BUD, TODAY))           # jamais dans la section voyage
        eco = Offer("CDG", "TYO", 500, depart=TODAY + timedelta(days=60), return_date=TODAY + timedelta(days=75))
        self.assertIsNone(evaluate.evaluate_business(eco, CFG, BUD, TODAY))      # ni l'inverse

    def test_preferences_and_dates_apply_to_business(self):
        self.assertIsNone(self.biz("TYO", 700, depart=TODAY + timedelta(days=3)))         # trop proche
        cfg = copy.deepcopy(CFG)
        cfg["excluded_countries"].append("JP")
        o = Offer("CDG", "TYO", 700, cabin="business")
        self.assertIsNone(evaluate.evaluate_business(o, cfg, BUD, TODAY))

    def test_too_expensive_feedback_lowers_business_cap(self):
        deal = {"kind": "business_deal", "offer": {"price_eur": 780, "dest": "TYO"}}
        p, msgs = preferences.learn(preferences.load_prefs(Path("/nonexistent")), "trop cher", deal, CFG)
        self.assertEqual(p["business_cap_eur"], 700)
        self.assertEqual(preferences.apply_prefs(CFG, p)["business"]["flight_cap_eur"], 700)


class Pepite(unittest.TestCase):
    """L'appli ne cherche pas un bon voyage : elle cherche la pépite (3 à 5 fois par an)."""

    def test_good_but_normal_deal_is_not_alerted(self):
        o = mk("ALA", 330, days=(60, 69))                                 # bon plan, direct, destination rare
        base = copy.deepcopy(LOOSE)
        score = evaluate.evaluate(o, base, {}, BUD, TODAY).score
        cfg = copy.deepcopy(CFG)
        cfg["scoring"]["min_score"] = score - 0.1
        self.assertTrue(cfg["scoring"]["require_anomaly"])
        self.assertIsNone(evaluate.evaluate(o, cfg, {}, BUD, TODAY))      # trop banal : on ne te dérange pas
        cfg["scoring"]["require_anomaly"] = False
        self.assertIsNotNone(evaluate.evaluate(o, cfg, {}, BUD, TODAY))   # il aurait passé sans l'exigence d'anomalie

    def test_real_anomaly_is_alerted(self):
        for kw, hist in (({"flagged_error": True}, {}), ({}, {"CDG-ALA-economy": [600, 620, 580, 610, 590, 640]})):
            v = evaluate.evaluate(mk("ALA", 200, days=(60, 69), **kw), CFG, hist, BUD, TODAY)
            self.assertIsNotNone(v)
            self.assertEqual(v.kind, "error_fare")

    def test_price_far_below_the_market_is_an_anomaly(self):
        # 25 % du prix habituel pour la distance, sans historique ni signalement : anomalie
        ref = scoring.reference_price(5400, "economy", CFG)
        v = evaluate.evaluate(mk("ALA", ref * 0.2, days=(60, 69)), CFG, {}, BUD, TODAY)
        self.assertIsNotNone(v)

    def test_rarity_percentile_is_shown(self):
        hist = {"CDG-ALA-economy": [600, 620, 580, 610, 590, 640, 650, 630]}
        v = evaluate.evaluate(mk("ALA", 200, days=(60, 69)), CFG, hist, BUD, TODAY)
        self.assertTrue(any("Moins cher que 100 %" in r for r in v.reasons))

    def test_yearly_counter(self):
        from datetime import datetime, timedelta, timezone
        from flightdeals import main
        now = datetime.now(timezone.utc)
        log = [{"at": (now - timedelta(days=d)).isoformat()} for d in (5, 100, 364, 400, 700)]
        orig = main._load
        main._load = lambda p, default: log if p == main.ALERTS else orig(p, default)
        try:
            self.assertEqual(main.alerts_last_year(now), 3)               # les alertes de plus d'un an ne comptent pas
        finally:
            main._load = orig

    def test_few_alerts_per_scan(self):
        self.assertLessEqual(CFG["max_alerts_per_run"]["scan"], 2)


if __name__ == "__main__":
    unittest.main()
