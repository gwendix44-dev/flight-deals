import copy
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flightdeals import evaluate, feedback, main, notify, pool as poolmod, preferences, verify
from flightdeals.common import dedupe_key
from flightdeals.core import Offer

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text())
LOOSE = copy.deepcopy(CFG)
LOOSE["scoring"]["min_score"] = 0
LOOSE["scoring"]["require_anomaly"] = False
LOOSE["publication"]["min_score"] = 0
BUD = evaluate.load_budgets()
U = timezone.utc


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=U)


def deal(dest, score, price=250, origin="CDG", depart_in=60, stay=15, airline="AF"):
    t = date.today()
    o = Offer(origin, dest, price, depart=t + timedelta(days=depart_in), return_date=t + timedelta(days=depart_in + stay),
              transfers=1, source="travelpayouts", link=f"https://x/{dest}", airline=airline)
    v = evaluate.evaluate(o, LOOSE, {}, BUD, t)
    assert v, dest
    v.score = score
    return v


class Sandbox(unittest.TestCase):
    """Fichiers temporaires, aucun réseau, aucune écriture dans le dépôt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = [(m, k, getattr(m, k)) for m, k in ((main, "SEEN"), (main, "DEALS"), (main, "STATUS"), (main, "ALERTS"),
                                                          (poolmod, "POOL"), (poolmod, "STATE"), (poolmod, "WATCH"),
                                                          (preferences, "PREFS_PATH"), (feedback, "LOG"), (feedback, "DEALS"))]
        main.SEEN, main.DEALS, main.STATUS, main.ALERTS = t / "seen.json", t / "deals.json", t / "status.json", t / "alerts.json"
        poolmod.POOL, poolmod.STATE, poolmod.WATCH = t / "pool.json", t / "state.json", t / "watch.json"
        preferences.PREFS_PATH, feedback.LOG, feedback.DEALS = t / "prefs.json", t / "feedback.json", main.DEALS
        self.issues, self.summaries, self.instants, self.empties = [], [], [], []
        self.o = (notify.create_issues, notify.send_push_summary, notify.send_push, notify.send_push_empty, verify.verify_all, feedback._api)
        notify.create_issues = lambda vs: (self.issues.append([v.dest_city for v in vs]), list(vs))[1]
        notify.send_push_summary = lambda vs, label: (self.summaries.append((label, [v.dest_city for v in vs])), list(vs))[1]
        notify.send_push = lambda vs: (self.instants.append([v.dest_city for v in vs]), list(vs))[1]
        notify.send_push_empty = lambda label, n, best: (self.empties.append((label, n, best)), True)[1]
        verify.verify_all = lambda vs, cfg, token, today, price_fn=None: [setattr(v, "verification", "ok") or v for v in vs]
        self.old_env = dict(os.environ)

    def tearDown(self):
        notify.create_issues, notify.send_push_summary, notify.send_push, notify.send_push_empty, verify.verify_all, feedback._api = self.o
        for m, k, v in self.saved:
            setattr(m, k, v)
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp.cleanup()

    def ctx(self, when):
        c = main.Ctx(False, when)
        c.cfg = copy.deepcopy(CFG)
        c.token = "t"
        return c


class RefusalParsing(unittest.TestCase):
    def test_issue_created_by_the_dashboard(self):
        r = feedback.parse_refusal_issue("Refus : CDG→Almaty", "deal:abc123def456\nissue:93\n---\ntrop cher, déjà vu")
        self.assertEqual(r, {"key": "abc123def456", "issue": 93, "reason": "trop cher, déjà vu"})
        self.assertEqual(feedback.parse_refusal_issue("Refus", "deal:abc123def456\nissue:\n---\ntrop loin")["issue"], 0)   # bon plan : pas d'Issue d'offre

    def test_other_issues_are_not_refusals(self):
        self.assertIsNone(feedback.parse_refusal_issue("Bug sur le dashboard", "deal:abc123def456\n---\nx"))

    def test_garbage_in_the_key_is_not_accepted(self):
        r = feedback.parse_refusal_issue("Refus", "deal:../../etc/passwd\n---\ntrop cher")
        self.assertEqual(r["key"], "")                                              # seule une empreinte hexadécimale est acceptée


class RefusalEndToEnd(Sandbox):
    def run_feedback(self, **env):
        calls = []
        feedback._api = lambda method, path, payload=None: calls.append((method, path, payload))
        os.environ.update({"GITHUB_REPOSITORY": "Moi/flight-deals", "GITHUB_REPOSITORY_OWNER": "Moi", "GITHUB_TOKEN": "t", **env})
        feedback.main()
        return calls

    def publish_one(self, dest="ALA", issue=93):
        v = deal(dest, 9.0)
        v.issue = issue
        main.publish([v], False, "Publication de 12h")
        return dedupe_key(v.offer), v

    def test_dashboard_refusal_learns_deletes_and_closes(self):
        key, v = self.publish_one()
        calls = self.run_feedback(EVENT_NAME="issues", ISSUE_USER="Moi", ISSUE_NUMBER="200", ISSUE_TITLE="Refus : CDG→Almaty",
                                  ISSUE_BODY=f"deal:{key}\nissue:93\n---\ntrop cher, destination déjà vue")
        prefs = preferences.load_prefs()
        self.assertIn(key, prefs["refused_keys"])                                   # l'offre est inscrite comme refusée
        self.assertIn(93, prefs["refused_issues"])
        self.assertIn("ALA", prefs["excluded_destinations"])                        # « destination déjà vue » est apprise
        self.assertTrue(prefs["cap_by_tier"])                                       # « trop cher » est appris aussi (budget baissé)
        self.assertLess(list(prefs["cap_by_tier"].values())[0], 1500)
        closed = sorted(p for m, p, _ in calls if m == "PATCH")
        self.assertEqual(closed, ["/issues/200", "/issues/93"])                     # l'Issue de refus ET l'Issue de l'offre sont fermées
        comment = next(pl for m, p, pl in calls if m == "POST")
        self.assertIn("supprimée", comment["body"])
        self.assertIn("/issues/200/comments", [p for m, p, _ in calls if m == "POST"])
        self.assertEqual(feedback._load(feedback.LOG, [])[0]["key"], key)           # journal des refus

    def test_comment_refusal_on_the_offer_issue(self):
        key, v = self.publish_one(issue=93)
        calls = self.run_feedback(EVENT_NAME="issue_comment", COMMENT_USER="Moi", ISSUE_NUMBER="93", COMMENT_BODY="séjour trop court")
        prefs = preferences.load_preferences() if hasattr(preferences, "load_preferences") else preferences.load_prefs()
        self.assertIn(key, prefs["refused_keys"])
        self.assertEqual(prefs["min_stay_extra"], 2)
        self.assertEqual([p for m, p, _ in calls if m == "PATCH"], ["/issues/93"])

    def test_bon_plan_without_issue_can_be_refused_by_key(self):
        key, v = self.publish_one(issue=0)
        v2 = main._load(main.DEALS, {})["deals"][0]
        self.assertFalse(v2.get("issue"))
        self.run_feedback(EVENT_NAME="issues", ISSUE_USER="Moi", ISSUE_NUMBER="201", ISSUE_TITLE="Refus : x",
                          ISSUE_BODY=f"deal:{key}\nissue:\n---\ntrop touristique")
        self.assertIn(key, preferences.load_prefs()["refused_keys"])
        self.assertIsNotNone(preferences.load_prefs()["min_secrecy"])

    def test_only_the_owner_is_listened_to(self):
        key, _ = self.publish_one()
        calls = self.run_feedback(EVENT_NAME="issues", ISSUE_USER="inconnu", ISSUE_NUMBER="202", ISSUE_TITLE="Refus : x",
                                  ISSUE_BODY=f"deal:{key}\nissue:93\n---\ntrop cher")
        self.assertEqual(calls, [])
        self.assertEqual(preferences.load_prefs()["refused_keys"], [])
        calls = self.run_feedback(EVENT_NAME="issue_comment", COMMENT_USER="github-actions[bot]", ISSUE_NUMBER="93", COMMENT_BODY="trop cher")
        self.assertEqual(calls, [])

    def test_reset_keeps_refused_offers_refused(self):
        key, _ = self.publish_one()
        self.run_feedback(EVENT_NAME="issues", ISSUE_USER="Moi", ISSUE_NUMBER="200", ISSUE_TITLE="Refus", ISSUE_BODY=f"deal:{key}\nissue:93\n---\ntrop cher")
        self.run_feedback(EVENT_NAME="issue_comment", COMMENT_USER="Moi", ISSUE_NUMBER="5", COMMENT_BODY="/reset")
        p = preferences.load_prefs()
        self.assertEqual(p["cap_by_tier"], {})
        self.assertIn(key, p["refused_keys"])                                       # /reset ne ressuscite pas une offre refusée


class RefusedOffersAreGone(Sandbox):
    def test_pruned_from_dashboard_reserve_and_watch_and_never_republished(self):
        c = self.ctx(utc(2026, 11, 12, 8, 0))
        keep, gone = deal("ALA", 9.0), deal("DKR", 9.0)
        gone.issue = 7
        main.publish([keep, gone], False, "Publication de 12h")
        poolmod.add(c.pool, gone, c.now_iso)
        poolmod.add(c.pool, keep, c.now_iso)
        poolmod.add(c.watch, gone, c.now_iso)
        k = dedupe_key(gone.offer)
        c.refused_keys = {k}
        main.prune_refused(c)
        self.assertEqual([d["dest_city"] for d in main._load(main.DEALS, {})["deals"]], ["Almaty"])   # disparu du dashboard
        self.assertEqual(len(c.pool), 1)                                                              # et de la réserve
        self.assertEqual(c.watch, [])                                                                 # et des bons plans
        self.assertEqual(main.fresh_candidates([gone], c.seen, CFG), [])                              # et ne revient jamais
        better = deal("DKR", 9.0, price=100)                                                          # même offre, encore moins chère : bloquée aussi
        self.assertEqual(main.fresh_candidates([better], c.seen, CFG), [])

    def test_refused_issue_number_also_removes_old_entries_without_key(self):
        c = self.ctx(utc(2026, 11, 12, 8, 0))
        v = deal("ALA", 9.0)
        v.issue = 55
        main.publish([v], False, "x")
        store = main._load(main.DEALS, {})
        store["deals"][0].pop("key")                                                                  # ancienne entrée sans clé
        main._save(main.DEALS, store)
        c.refused_issues = {55}
        main.prune_refused(c)
        self.assertEqual(main._load(main.DEALS, {})["deals"], [])


class Cooldown(Sandbox):
    def log(self, dest, price, days_ago, kind="deal"):
        entries = main._load(main.ALERTS, [])
        entries.append({"at": (datetime.now(U) - timedelta(days=days_ago)).isoformat(), "route": f"CDG-{dest}", "price": price, "kind": kind})
        main._save(main.ALERTS, entries)

    def test_same_destination_is_not_republished_within_the_week_unless_much_cheaper(self):
        self.log("ALA", 200, 2)
        cd = main.recent_dests(datetime.now(U), 7)
        self.assertEqual(cd, {("ALA", "std"): 200})
        again, cheaper, other = deal("ALA", 9, price=190), deal("ALA", 9, price=140, depart_in=70), deal("DKR", 9, price=190)
        out = main.fresh_candidates([again, cheaper, other], {}, CFG, None, cd)
        self.assertEqual(sorted((v.dest_city, v.offer.price_eur) for v in out), [("Almaty", 140), ("Dakar", 190)])   # -25 % mini pour revenir

    def test_cooldown_expires_after_a_week(self):
        self.log("ALA", 200, 9)
        self.assertEqual(main.recent_dests(datetime.now(U), 7), {})

    def test_business_and_standard_do_not_block_each_other(self):
        self.log("TYO", 700, 1, kind="business_deal")
        cd = main.recent_dests(datetime.now(U), 7)
        self.assertEqual(main.fresh_candidates([deal("TYO", 9, price=250)], {}, CFG, None, cd).__len__(), 1)

    def test_old_alert_entries_without_dest_field_still_count(self):
        self.log("SID", 91, 1)                                                                          # format d'avant : seulement « route »
        self.assertIn(("SID", "std"), main.recent_dests(datetime.now(U), 7))

    def test_one_route_cannot_fill_every_slot(self):
        c = self.ctx(utc(2026, 11, 12, 11, 5))
        self.log("SID", 120, 1)                                                                        # Cap-Vert déjà publié hier
        c.cooldown = main.recent_dests(c.now_utc, 7)
        for d, sc in (("SID", 9.4), ("ALA", 8.6), ("DKR", 8.2)):
            poolmod.add(c.pool, deal(d, sc, price=110 if d == "SID" else 250), c.now_iso)
        main.tick_slots(c)
        shown = [d["dest_city"] for d in main._load(main.DEALS, {})["deals"] if d.get("tier") == "pepite"]
        self.assertNotIn("Cap-Vert (Sal)", shown)                                                      # pas une 6e fois de suite
        self.assertIn("Almaty", shown)


class EmptySlotAndBonsPlans(Sandbox):
    def test_an_empty_slot_is_never_silent(self):
        c = self.ctx(utc(2026, 11, 12, 11, 5))
        c.near_raw = [(7.4, "CDG→Bangkok 380€ : prix 2/3 …"), (7.1, "LIS→Dakar 200€ …")]
        main.tick_slots(c)
        self.assertEqual(self.summaries, [])                                           # aucune pépite à annoncer
        self.assertEqual(len(self.empties), 1)                                         # mais une notification explique pourquoi
        label, n_bp, best = self.empties[0]
        self.assertEqual(label, "Publication de 12h")
        self.assertIn("Bangkok", best[0])
        self.assertEqual(c.state["last_slot"]["best_missed"][0][:3], "7.4")
        self.assertIn("2026-11-12@12:00", c.state["published"])

    def test_empty_slot_notification_can_be_turned_off(self):
        c = self.ctx(utc(2026, 11, 12, 11, 5))
        c.cfg["publication"]["notify_empty_slots"] = False
        main.tick_slots(c)
        self.assertEqual(self.empties, [])

    def test_bons_plans_one_per_region_without_alert_or_issue(self):
        c = self.ctx(utc(2026, 11, 12, 11, 5))
        for dest, sc in (("BKK", 7.6), ("HKT", 7.4), ("SGN", 7.2), ("BOG", 7.3), ("DKR", 7.1), ("ACC", 7.0)):
            poolmod.add(c.watch, deal(dest, sc), c.now_iso)
        main.tick_slots(c)
        bp = [d for d in main._load(main.DEALS, {})["deals"] if d.get("tier") == "bon_plan"]
        from flightdeals.airports import region_of
        regions = [region_of(d["country"]) for d in bp]
        self.assertEqual(len(regions), len(set(regions)))                              # une seule par région : pas que l'Asie
        self.assertGreaterEqual(len(set(regions)), 2)
        self.assertLessEqual(len(bp), 4)
        self.assertEqual(self.issues, [])                                              # jamais d'Issue ni de notification pour un bon plan
        self.assertEqual(self.summaries, [])
        self.assertEqual(self.empties[0][1], len(bp))                                  # la notification du créneau vide les mentionne

    def test_bon_plan_is_not_shown_again_for_three_days(self):
        c = self.ctx(utc(2026, 11, 12, 11, 5))
        poolmod.add(c.watch, deal("BKK", 7.6), c.now_iso)
        main.tick_slots(c)
        self.assertEqual(len([d for d in main._load(main.DEALS, {})["deals"] if d.get("tier") == "bon_plan"]), 1)
        c.now_utc = utc(2026, 11, 12, 18, 5)
        poolmod.add(c.watch, deal("BKK", 7.7, depart_in=70), c.now_iso)
        main.tick_slots(c)
        self.assertEqual(len([d for d in main._load(main.DEALS, {})["deals"] if d.get("tier") == "bon_plan"]), 1)   # pas re-proposé le soir

    def test_old_bons_plans_leave_the_dashboard(self):
        c = self.ctx(utc(2026, 11, 12, 8, 0))
        v = deal("BKK", 7.5)
        main.publish([v], False, "Publication de 12h", tier="bon_plan")
        store = main._load(main.DEALS, {})
        store["deals"][0]["found_at"] = (c.now_utc - timedelta(hours=40)).isoformat()
        main._save(main.DEALS, store)
        main.prune_refused(c)
        self.assertEqual(main._load(main.DEALS, {})["deals"], [])

    def test_watch_threshold_collects_7_to_8_only(self):
        evaluate.WATCH.clear()
        cfg = copy.deepcopy(CFG)
        o = Offer("CDG", "ALA", 330, depart=date.today() + timedelta(days=60), return_date=date.today() + timedelta(days=75),
                  transfers=0, airline="AF", source="travelpayouts")
        score = evaluate.evaluate(o, LOOSE, {}, BUD, date.today()).score
        cfg["publication"]["min_score"] = cfg["scoring"]["min_score"] = round(score + 0.1, 1)         # juste sous le seuil
        cfg["publication"]["watch_min"] = round(score - 0.5, 1)
        self.assertIsNone(evaluate.evaluate(o, cfg, {}, BUD, date.today()))
        self.assertEqual(len(evaluate.WATCH), 1)                                                       # gardée comme bon plan
        evaluate.WATCH.clear()
        cfg["publication"]["watch_min"] = round(score + 0.05, 1)                                       # sous le plancher des bons plans
        evaluate.evaluate(o, cfg, {}, BUD, date.today())
        self.assertEqual(evaluate.WATCH, [])


class Diagnostics(Sandbox):
    def test_status_explains_what_was_found_and_rejected(self):
        c = self.ctx(utc(2026, 11, 12, 8, 0))
        c.near_raw = [(7.4, "CDG→Bangkok 380€ …")]
        verify.DROPPED.clear()
        verify.DROPPED.append("CDG→Almaty 288€ : prix remonté de 288 à 410 €")
        main.write_status(c, "scan")
        st = json.loads(main.STATUS.read_text())
        self.assertIn("Bangkok", st["best_missed"][0])
        self.assertIn("prix remonté", st["rejets"][0])


if __name__ == "__main__":
    unittest.main()
