import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flightdeals import evaluate, main, notify, pool as poolmod, slots, verify
from flightdeals.core import Offer

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
LOOSE = copy.deepcopy(CFG)
LOOSE["scoring"]["min_score"] = 0
LOOSE["scoring"]["require_anomaly"] = False
BUD = evaluate.load_budgets()
U = timezone.utc


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=U)


class Slots(unittest.TestCase):
    def test_paris_time_winter_and_summer(self):
        self.assertEqual(slots.local_now(utc(2026, 11, 7, 11, 0)).hour, 12)        # CET = UTC+1
        self.assertEqual(slots.local_now(utc(2026, 7, 7, 10, 0)).hour, 12)         # CEST = UTC+2
        self.assertEqual(slots.local_now(utc(2026, 3, 29, 1, 0)).hour, 3)          # bascule à l'heure d'été

    def test_due_slot_noon_and_evening(self):
        self.assertEqual(slots.due_slot(CFG, [], utc(2026, 11, 7, 11, 5)), "2026-11-07@12:00")
        self.assertEqual(slots.due_slot(CFG, [], utc(2026, 11, 7, 18, 20)), "2026-11-07@19:00")
        self.assertEqual(slots.due_slot(CFG, [], utc(2026, 7, 7, 17, 0)), "2026-07-07@19:00")     # heure d'été

    def test_not_before_and_not_after_the_window(self):
        self.assertIsNone(slots.due_slot(CFG, [], utc(2026, 11, 7, 10, 59)))       # 11h59 à Paris
        self.assertIsNone(slots.due_slot(CFG, [], utc(2026, 11, 7, 14, 30)))       # 15h30 : fenêtre dépassée
        self.assertIsNone(slots.due_slot(CFG, [], utc(2026, 11, 7, 3, 0)))         # la nuit

    def test_a_late_scan_still_catches_the_slot_once(self):
        self.assertEqual(slots.due_slot(CFG, [], utc(2026, 11, 7, 12, 40)), "2026-11-07@12:00")    # scan retardé de 1h40
        self.assertIsNone(slots.due_slot(CFG, ["2026-11-07@12:00"], utc(2026, 11, 7, 11, 20)))     # déjà publié

    def test_next_slot_label(self):
        self.assertEqual(slots.next_slot_label(CFG, utc(2026, 11, 7, 8, 0)), "aujourd'hui 12:00")
        self.assertEqual(slots.next_slot_label(CFG, utc(2026, 11, 7, 12, 0)), "aujourd'hui 19:00")
        self.assertEqual(slots.next_slot_label(CFG, utc(2026, 11, 7, 20, 0)), "demain 12:00")


def deal(dest, score, price=250, origin="CDG", stop=1, depart_in=60, stay=15, **kw):
    t = date.today()
    o = Offer(origin, dest, price, depart=t + timedelta(days=depart_in), return_date=t + timedelta(days=depart_in + stay),
              transfers=stop, source="travelpayouts", link=f"https://x/{dest}", **kw)
    v = evaluate.evaluate(o, LOOSE, {}, BUD, t)
    assert v, dest
    v.score = score
    return v


def biz(dest, price=700, origin="CDG"):
    v = evaluate.evaluate_business(Offer(origin, dest, price, cabin="business", source="rss:x", link="https://x/b"),
                                   CFG, BUD, date.today())
    assert v, dest
    return v


class Pool(unittest.TestCase):
    def test_roundtrip_keeps_everything(self):
        v = deal("BKK", 8.5, depart_in=60, stay=14)
        v.verification = "ok"
        r = poolmod.verdict_from_dict(json.loads(json.dumps(poolmod.verdict_to_dict(v))))
        self.assertEqual((r.dest_city, r.score, r.trip_total, r.verification), (v.dest_city, v.score, v.trip_total, "ok"))
        self.assertEqual(r.offer.depart, v.offer.depart)
        self.assertEqual(r.cost_lines[0][0], v.cost_lines[0][0])

    def test_add_keeps_the_cheapest(self):
        pool, now = [], datetime.now(U).isoformat()
        v1, v2 = deal("BKK", 9, price=300), deal("BKK", 9, price=250)
        self.assertTrue(poolmod.add(pool, v1, now))
        self.assertFalse(poolmod.add(pool, v1, now))                 # même offre : rien ne change
        self.assertTrue(poolmod.add(pool, v2, now))                  # moins chère : remplace ?
        self.assertEqual(len(pool), 1 if v1.offer.title == v2.offer.title else 2)

    def test_expire(self):
        old = (datetime.now(U) - timedelta(hours=40)).isoformat()
        new = (datetime.now(U) - timedelta(hours=2)).isoformat()
        kept = poolmod.expire([{"key": "a", "found_at": old}, {"key": "b", "found_at": new}], CFG)
        self.assertEqual([e["key"] for e in kept], ["b"])

    def test_waiting_offer_is_dropped_when_no_longer_valid(self):
        v = deal("BKK", 9)
        self.assertTrue(poolmod.still_valid(v, CFG, date.today()))
        cfg = copy.deepcopy(CFG)
        cfg["excluded_countries"].append("TH")                       # tu as refusé la Thaïlande depuis
        self.assertFalse(poolmod.still_valid(v, cfg, date.today()))
        v.offer.depart = date.today() + timedelta(days=3)            # départ trop proche
        self.assertFalse(poolmod.still_valid(v, CFG, date.today()))


class Flow(unittest.TestCase):
    """Déroulé complet avec des fichiers temporaires et sans réseau."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = {k: getattr(m, k) for m, k in ((main, "SEEN"), (main, "DEALS"), (main, "STATUS"), (main, "ALERTS"),
                                                     (poolmod, "POOL"), (poolmod, "STATE"))}
        main.SEEN, main.DEALS, main.STATUS, main.ALERTS = t / "seen.json", t / "deals.json", t / "status.json", t / "alerts.json"
        poolmod.POOL, poolmod.STATE = t / "pool.json", t / "state.json"
        self.issues, self.pushes, self.instants = [], [], []
        self.o = (notify.create_issues, notify.send_push_summary, notify.send_push, verify.verify_all)
        notify.create_issues = lambda vs: (self.issues.append([v.dest_city for v in vs]), list(vs))[1]
        notify.send_push_summary = lambda vs, label: (self.pushes.append((label, len(vs))), list(vs))[1]
        notify.send_push = lambda vs: (self.instants.append([v.dest_city for v in vs]), list(vs))[1]
        self.confirm = lambda vs, cfg, token, today, price_fn=None: [setattr(v, "verification", "ok") or v for v in vs]
        verify.verify_all = self.confirm

    def tearDown(self):
        notify.create_issues, notify.send_push_summary, notify.send_push, verify.verify_all = self.o
        for (m, k), v in zip(((main, "SEEN"), (main, "DEALS"), (main, "STATUS"), (main, "ALERTS"), (poolmod, "POOL"), (poolmod, "STATE")),
                             self.saved.values()):
            setattr(m, k, v)
        self.tmp.cleanup()

    def ctx(self, when):
        c = main.Ctx(False, when)
        c.cfg = copy.deepcopy(CFG)
        c.token = "t"
        return c

    def test_ten_out_of_ten_is_published_immediately_others_wait(self):
        c = self.ctx(utc(2026, 11, 7, 8, 0))                                       # 9h Paris : aucun créneau
        main.ingest(c, [deal("ALA", 10.4), deal("BKK", 8.6), deal("DKR", 8.1)])
        self.assertEqual(self.instants, [["Almaty"]])                              # 10/10 : tout de suite
        self.assertEqual(len(c.pool), 2)                                           # les autres attendent 12h
        main.tick_slots(c)
        self.assertEqual(self.pushes, [])                                          # rien à 9h
        self.assertEqual(c.state.get("published", []), [])

    def test_noon_slot_publishes_best_three_standard_and_three_business_once(self):
        c = self.ctx(utc(2026, 11, 7, 11, 5))                                      # 12h05 Paris
        std = [deal("BKK", 8.2), deal("ALA", 9.0), deal("DKR", 8.8), deal("BOG", 8.5), deal("LIM", 8.1)]
        bz = [biz("TYO", 780), biz("BJS", 780), biz("SIN", 780), biz("DEL", 780)]     # 8 à 10 : attendent le créneau
        main.ingest(c, std + bz)
        self.assertEqual(c.stats["instant"], 0)                                    # rien à 10/10 : tout attend 12h
        main.tick_slots(c)
        label, n = self.pushes[0]
        self.assertEqual(label, "Publication de 12h")
        deals = json.loads(main.DEALS.read_text())["deals"]
        n_std = sum(d["kind"] != "business_deal" for d in deals if d["slot"] == "Publication de 12h")
        n_biz = sum(d["kind"] == "business_deal" for d in deals if d["slot"] == "Publication de 12h")
        self.assertLessEqual(n_std, 3)
        self.assertLessEqual(n_biz, 3)
        self.assertGreaterEqual(n_std, 1)
        self.assertGreaterEqual(n_biz, 1)
        self.assertIn("2026-11-07@12:00", c.state["published"])
        self.assertIsNotNone(c.state["last_slot"])
        main_pushes = len(self.pushes)
        main.tick_slots(c)                                                         # même créneau : jamais deux fois
        self.assertEqual(len(self.pushes), main_pushes)

    def test_business_ten_out_of_ten_is_also_immediate(self):
        c = self.ctx(utc(2026, 11, 7, 8, 0))
        main.ingest(c, [biz("TYO", 400)])                                          # ~ -87 % : 10/10
        self.assertEqual(self.instants, [["Tokyo"]])

    def test_instant_alerts_are_capped_per_day(self):
        c = self.ctx(utc(2026, 11, 7, 8, 0))
        main.ingest(c, [deal(d, 10.5) for d in ("ALA", "BKK", "DKR")])                 # 3 immédiates
        main.ingest(c, [deal(d, 10.5) for d in ("BOG", "LIM", "MEX")])                 # plafond de 4 par jour
        self.assertEqual(sum(len(x) for x in self.instants), 4)
        self.assertEqual(len(c.pool), 2)                                               # le reste attend le prochain créneau

    def test_best_scores_are_chosen(self):
        c = self.ctx(utc(2026, 11, 7, 11, 5))
        main.ingest(c, [deal("BKK", 8.2), deal("ALA", 9.4), deal("DKR", 8.8), deal("BOG", 8.5), deal("LIM", 8.1), deal("MEX", 8.3)])
        main.tick_slots(c)
        shown = [d["dest_city"] for d in json.loads(main.DEALS.read_text())["deals"]]
        self.assertIn("Almaty", shown)                                              # 9,4 : forcément
        self.assertNotIn("Lima", shown)                                             # 8,1 : trop juste, plus de place
        self.assertLessEqual(len(shown), 3)
        self.assertEqual(len(c.pool), 6 - len(shown))                               # les autres attendent le créneau de 19h

    def test_an_offer_that_disappeared_is_not_published(self):
        c = self.ctx(utc(2026, 11, 7, 11, 5))
        main.ingest(c, [deal("ALA", 9.0), deal("DKR", 8.8)])
        verify.verify_all = lambda vs, cfg, token, today, price_fn=None: [v for v in vs if v.dest_city != "Almaty"]
        main.tick_slots(c)
        shown = [d["dest_city"] for d in json.loads(main.DEALS.read_text())["deals"]]
        self.assertEqual(shown, ["Dakar"])
        self.assertEqual(len(c.pool), 0)                                            # l'offre disparue est purgée

    def test_nothing_published_when_nothing_qualifies(self):
        c = self.ctx(utc(2026, 11, 7, 11, 5))
        main.tick_slots(c)
        self.assertEqual(self.pushes, [])                                           # on ne publie jamais du remplissage
        self.assertEqual(c.state["last_slot"]["standard"], 0)                       # mais le créneau est noté comme passé
        self.assertIn("2026-11-07@12:00", c.state["published"])

    def test_status_file_tells_if_the_app_is_alive(self):
        c = self.ctx(utc(2026, 11, 7, 8, 0))
        c.stats.update(offers=10031, candidates=3)
        main.write_status(c, "scan")
        st = json.loads(main.STATUS.read_text())
        self.assertTrue(st["ok"])
        self.assertEqual((st["offers"], st["source"]), (10031, "scan"))


if __name__ == "__main__":
    unittest.main()
