import json
import random
import unittest
from datetime import timedelta

from flightdeals import feedback, main, prefs as P, publish as PB
from flightdeals.util import read_json
from helpers import RAW, TODAY, fake_fetch, noon, row, sandbox, stop


class ScanBase(unittest.TestCase):
    def setUp(self):
        self.tmp, self._ps = sandbox()
        self.pushes, self.issues = [], []
        self.n = 0

    def tearDown(self):
        stop(self._ps)

    def issue(self, d):
        self.n += 1
        self.issues.append(d["key"])
        return 100 + self.n

    def scan(self, rows, now, prefs=None, rss=None):
        return main.run_scan(now=now, token="t", push=lambda *a, **k: self.pushes.append((a, k)), issue=self.issue,
                             fetch=fake_fetch(rows), rss=rss or (lambda u: b"<rss></rss>"), errors=[], cfg=RAW,
                             prefs=prefs if prefs is not None else P.load())


GOOD = {"CDG": [row("SAL", 250, airline="TP"), row("ALA", 300), row("KTM", 380, airline="QR")]}


class Publication(ScanBase):
    def test_slot_publishes_and_notifies_once(self):
        st, s = self.scan(GOOD, noon())
        self.assertEqual(s["last_slot"]["id"], "2026-11-21@12:00")
        self.assertEqual(len([p for p in self.pushes if p[1].get("tag", "").startswith("slot")]), 1)
        deals = read_json(self.tmp / "docs/deals.json")
        self.assertEqual(len(deals["deals"]), s["last_slot"]["standard"])
        self.assertEqual(len(self.issues), s["last_slot"]["standard"] + s["last_slot"]["business"])

    def test_slot_not_republished_on_next_scan(self):
        self.scan(GOOD, noon())
        n = len(self.pushes)
        self.scan(GOOD, noon(mm=40))
        self.assertEqual(len(self.pushes), n)

    def test_empty_slot_never_silent_and_no_filler(self):
        st, s = self.scan({"CDG": [row("BKK", 900)]}, noon())
        self.assertEqual(s["last_slot"]["standard"], 0)
        self.assertIn("rien d'exceptionnel", self.pushes[-1][0][0])
        self.assertTrue(s["last_slot"]["best_missed"] or s["best_missed"] is not None)

    def test_max_three_standard(self):
        rows = {"CDG": [row(d, 250) for d in ("SAL", "ALA", "KTM", "FRU", "TAS", "ULN", "KGL")]}
        st, s = self.scan(rows, noon())
        self.assertLessEqual(s["last_slot"]["standard"], 3)

    def test_cooldown_same_destination_week(self):
        self.scan(GOOD, noon())
        st, s = self.scan(GOOD, noon(hh=18, mm=10))
        pub = [d["dest"] for d in read_json(self.tmp / "docs/deals.json")["deals"]]
        self.assertEqual(len(pub), len(set(pub)))

    def test_price_gone_at_reverification_is_dropped(self):
        def fetch(params, token):
            rows = GOOD["CDG"] if not params.get("destination") else []
            return rows
        st, s = main.run_scan(now=noon(), token="t", push=lambda *a, **k: None, issue=self.issue, fetch=fetch,
                              rss=lambda u: b"", errors=[], cfg=RAW, prefs=P.load())
        self.assertEqual(s["last_slot"]["standard"], 0)

    def test_api_error_captured_not_crashing(self):
        def boom(params, token):
            raise OSError("réseau")
        errors = []
        st, s = main.run_scan(now=noon(), token="t", push=lambda *a, **k: None, issue=self.issue, fetch=boom,
                              rss=lambda u: b"", errors=errors, cfg=RAW, prefs=P.load())
        self.assertFalse(s["ok"])
        self.assertTrue(s["errors"])

    def test_instant_needs_second_observation(self):
        rows = {"CDG": [row("SAL", 120, airline="TP", stay=10)]}
        self.scan(rows, noon(hh=9, mm=0))
        first = [p for p in self.pushes if p[1].get("tag") == "instant"]
        self.scan(rows, noon(hh=9, mm=20))
        second = [p for p in self.pushes if p[1].get("tag") == "instant"]
        self.assertEqual(len(first), 0)
        self.assertLessEqual(len(second), 1)

    def test_refused_offer_removed_everywhere_forever(self):
        self.scan(GOOD, noon())
        deal = read_json(self.tmp / "docs/deals.json")["deals"][0]
        cfg = RAW
        feedback.refuse(deal["key"], "pas intéressant", cfg, [deal["issue"]])
        deals = read_json(self.tmp / "docs/deals.json")
        self.assertNotIn(deal["key"], [d["key"] for d in deals["deals"]])
        self.scan(GOOD, noon(hh=18, mm=10))
        deals = read_json(self.tmp / "docs/deals.json")
        self.assertNotIn(deal["dest"], [d["dest"] for d in deals["deals"]])

    def test_status_written(self):
        self.scan(GOOD, noon())
        s = read_json(self.tmp / "docs/status.json")
        self.assertTrue(s["ok"])
        self.assertIn("next_slot", s)

    def test_rss_business_error_fare_published(self):
        feed = b"<rss><channel><item><title>Madrid to Bogota in Business Class for EUR 790 return - error fare</title><link>https://x</link></item></channel></rss>"
        feed = feed.replace(b"EUR 790", "€790".encode())
        st, s = self.scan({}, noon(), rss=lambda u: feed)
        self.assertGreaterEqual(s["last_slot"]["business"], 0)


class Feedback(ScanBase):
    def test_reasons_harden(self):
        deal = {"km": 9000, "total": 1480, "stay_days": 14, "hours": 12, "transfers": 1, "dest": "KTM", "dest_city": "Katmandou",
                "depart": "2027-02-10", "kind": "standard"}
        p = dict(P.DEFAULT, cap_by_tier={}, excluded_destinations=[], excluded_months=[])
        for reason, field in [("Trop cher", "cap_by_tier"), ("Séjour trop court", "min_stay_extra"), ("Trop loin", "max_distance_km"),
                              ("Trop d'escales", "max_transfers"), ("Avion pas adapté", "strict_aircraft"),
                              ("Billets séparés", "stopovers_disabled"), ("Pas envie", "excluded_destinations"),
                              ("Mauvaise période", "excluded_months"), ("Trop touristique", "min_secrecy"), ("Bof", "min_score_bonus")]:
            q = json.loads(json.dumps(p))
            fx = feedback.apply_reason(q, reason, deal, RAW)
            self.assertTrue(fx, reason)
            self.assertTrue(q[field] or q[field] == 0 and q[field] is not None, reason)

    def test_max_amount_in_reason(self):
        p = json.loads(json.dumps(P.DEFAULT))
        feedback.apply_reason(p, "max 1100 €", {"km": 5000, "total": 1400, "kind": "standard"}, RAW)
        self.assertEqual(p["cap_by_tier"]["0"], 1100)

    def test_unknown_reason_still_deletes(self):
        self.scan(GOOD, noon())
        deal = read_json(self.tmp / "docs/deals.json")["deals"][0]
        res = feedback.refuse(deal["key"], "blabla", RAW, [])
        self.assertFalse(res["recognized"])
        self.assertIn(deal["key"], P.load()["refused_keys"])

    def test_reset_keeps_refusals(self):
        p = P.load()
        p["strict_aircraft"], p["refused_keys"] = True, ["abc"]
        P.save(p)
        feedback.reset()
        q = P.load()
        self.assertFalse(q["strict_aircraft"])
        self.assertEqual(q["refused_keys"], ["abc"])

    def test_body_parsing(self):
        self.assertEqual(feedback.parse_refusal_body("deal:0123456789abcdef\nissue:7\n---\nTrop cher"), ("0123456789abcdef", 7, "Trop cher"))


class Fuzz(ScanBase):
    def test_random_offers_never_crash(self):
        rnd = random.Random(42)
        from flightdeals.world import world
        dests = list(world()["destinations"])
        for i in range(25):
            rows = {o: [row(rnd.choice(dests), rnd.choice([5, 40, 90, 1000, 0]), days_out=rnd.choice([-5, 3, 20, 100, 300]),
                            stay=rnd.choice([0, 3, 14, 30]), airline=rnd.choice(["KL", "FR", "ZZ", ""]), transfers=rnd.choice([0, 1, 2, 4]))
                        for _ in range(30)] for o in ("CDG", "NTE", "FRA")}
            st, s = self.scan(rows, noon(hh=11 + i % 2, mm=i))
            self.assertIn("ok", s)


if __name__ == "__main__":
    unittest.main()
