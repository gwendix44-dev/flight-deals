"""Point d'entrée : python -m flightdeals.main [--demo] [--dry-run]

Fonctionnement (scan toutes les 15 min) :
  1. collecte des prix et évaluation (note /11) ;
  2. les offres >= 8/10 sont revérifiées (prix pour les dates exactes) ;
  3. 10/10 : publiées et notifiées immédiatement ;
     8 à 10 : mises en réserve (data/pool.json) ;
  4. à 12h et 19h (heure de Paris) : les 3 meilleurs deals standard + les 3 meilleures offres business de la réserve sont
     revérifiés une dernière fois, publiés sur le dashboard et notifiés.
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import evaluate, notify, pool as poolmod, preferences, providers, slots, verify
from .airports import DESTINATIONS, region_of
from .common import ROOT, _load, _save, dedupe_key, months_ahead   # noqa: F401  (ré-exportés : combos, feedback, tests)

HISTORY = ROOT / "data" / "history.json"
SEEN = ROOT / "data" / "seen.json"
DEALS = ROOT / "docs" / "deals.json"
STATUS = ROOT / "docs" / "status.json"
ALERTS = ROOT / "data" / "alerts_log.json"      # journal des alertes envoyées


def alerts_last_year(now=None) -> int:
    now = now or datetime.now(timezone.utc)
    n = 0
    for a in _load(ALERTS, []):
        try:
            if (now - datetime.fromisoformat(a["at"])).days < 365:
                n += 1
        except (KeyError, ValueError):
            pass
    return n


# ----------------------------------------------------------------------------------------------- sélection
def fresh_candidates(candidates: list, seen: dict, cfg: dict, waiting: Optional[dict] = None) -> list:
    """Offres jamais publiées (ou au moins X % moins chères que la dernière publication), pas déjà en réserve à ce prix."""
    drop = 1 - cfg["realert_if_price_drops_pct"] / 100
    out = []
    for v in candidates:
        k = dedupe_key(v.offer)
        prev = seen.get(k)
        if prev is not None and v.offer.price_eur > prev * drop:
            continue
        if waiting and k in waiting and v.offer.price_eur >= waiting[k]:
            continue
        out.append(v)
    out.sort(key=lambda v: (-v.score, v.offer.price_eur if v.kind == "business_deal" else v.trip_total))
    return out


def select_top(fresh: list, cfg: dict, limit: int) -> list:
    """Toute la planète : on prend à tour de rôle la meilleure offre de chaque région du monde (Asie, Amérique du Nord,
    Amérique latine, Afrique, Océanie, Moyen-Orient), au plus N par région et une seule par destination."""
    by_region: dict = {}
    for v in fresh:                                           # `fresh` est déjà trié par note décroissante
        by_region.setdefault(region_of(v.country), []).append(v)
    top, dests, taken = [], set(), {r: 0 for r in by_region}
    while len(top) < limit:
        heads = []
        for r, lst in by_region.items():
            while lst and lst[0].offer.dest in dests:
                lst.pop(0)
            if lst and taken[r] < cfg.get("max_alerts_per_region", 2):
                heads.append(lst[0])
        if not heads:
            break
        best = max(heads, key=lambda v: v.score)
        by_region[region_of(best.country)].pop(0)
        taken[region_of(best.country)] += 1
        dests.add(best.offer.dest)
        top.append(best)
    return top


def dispatch(candidates, seen: dict, cfg: dict, dry: bool, limit: int, verifier=None) -> list:
    """Sélection directe (sans créneau) : utilisée par les tests et les essais à blanc."""
    fresh = fresh_candidates(candidates, seen, cfg)
    if verifier:
        fresh = verifier(fresh)
    top = select_top(fresh, cfg, limit)
    print(f"{len(candidates)} affaires, {len(fresh)} nouvelles, {len(top)} retenues")
    if dry:
        for v in top:
            print("\n" + notify.body(v))
    return top


# -------------------------------------------------------------------------------------------- publication
def announce(top: list, seen: dict, label: str, dry: bool, summary: bool) -> list:
    """Issues GitHub (une par offre, pour pouvoir refuser) + notification push. Ne marque « vues » que les offres réellement
    notifiées : un échec d'envoi ne les perd pas."""
    if not top:
        return []
    for v in top:
        v.reasons.append(label)
    if dry:
        for v in top:
            print("\n" + notify.body(v))
        return top
    sent_issues = notify.create_issues(top)
    pushed = notify.send_push_summary(top, label) if summary else notify.send_push(top)
    sent = list({id(v): v for v in [*sent_issues, *pushed]}.values())
    if sent:
        log = _load(ALERTS, [])
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for v in sent:
            log.append({"at": now_iso, "route": f"{v.offer.origin}-{v.offer.dest}", "price": v.offer.price_eur,
                        "kind": v.kind, "label": label})
            k = dedupe_key(v.offer)
            seen[k] = min(v.offer.price_eur, seen.get(k, 1e9))
        _save(ALERTS, log[-200:])
    print(f"{label} : {len(sent)} offre(s) notifiée(s) (Issues : {len(sent_issues)}, push : {len(pushed)})")
    return top      # le dashboard affiche tout ce qui a été publié, même si l'envoi a échoué


def publish(top: list, dry: bool, label: str = "") -> None:
    """Met à jour le dashboard (docs/deals.json), sans doublons."""
    if dry or not top:
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store = _load(DEALS, {"deals": []})
    keys = {dedupe_key(v.offer) for v in top}
    old = [d for d in store.get("deals", []) if d.get("key") not in keys]
    store["updated"] = now
    store["deals"] = ([dict(v.to_dict(), found_at=now, key=dedupe_key(v.offer), slot=label) for v in top] + old)[:200]
    _save(DEALS, store)


# ------------------------------------------------------------------------------------------ déroulé commun
class Ctx:
    """État d'un scan : configuration, fichiers d'état, compteurs."""

    def __init__(self, dry: bool, now_utc: Optional[datetime] = None):
        self.dry = dry
        self.now_utc = now_utc or datetime.now(timezone.utc)
        self.today = self.now_utc.date()
        self.cfg = preferences.load_cfg()
        self.token = os.environ.get("TRAVELPAYOUTS_TOKEN")
        self.seen = _load(SEEN, {})
        self.pool = poolmod.load_pool()
        self.state = _load(poolmod.STATE, {"published": []})
        self.stats: dict = {}
        self.errors: list = []

    @property
    def now_iso(self) -> str:
        return self.now_utc.isoformat(timespec="seconds")

    def save(self) -> None:
        if self.dry:
            return
        poolmod.save_pool(self.pool)
        _save(SEEN, dict(list(self.seen.items())[-5000:]))
        self.state["published"] = self.state.get("published", [])[-20:]
        _save(poolmod.STATE, self.state)


def ingest(ctx: Ctx, candidates: list) -> None:
    """Offres ≥ 8/10 -> revérification -> 10/10 : publication immédiate ; sinon : mise en réserve jusqu'au prochain créneau."""
    pub = ctx.cfg["publication"]
    fresh = fresh_candidates(candidates, ctx.seen, ctx.cfg, poolmod.waiting_keys(ctx.pool))
    verified = verify.verify_all(fresh, ctx.cfg, ctx.token, ctx.today) if fresh else []
    # Garde-fou : une donnée fausse ne doit pas inonder ton téléphone. Au-delà du plafond quotidien, les 10/10 attendent le créneau.
    day_ago = ctx.now_utc - timedelta(hours=24)
    today_instants = 0
    for a in _load(ALERTS, []):
        try:
            if a.get("label", "").startswith("⚡") and datetime.fromisoformat(a["at"]) > day_ago:
                today_instants += 1
        except (KeyError, ValueError):
            pass
    room = max(0, pub.get("instant_max_per_day", 4) - today_instants)
    instant = [v for v in verified if v.score >= pub["instant_score"]][:min(3, room)]
    for v in verified:
        if v not in instant and not ctx.dry:
            poolmod.add(ctx.pool, v, ctx.now_iso)
    ctx.stats.update(candidates=len(candidates), verified=len(verified), instant=len(instant))
    if instant:
        instant, _dropped = verify.live_confirm(instant, ctx.cfg, ctx.today, len(instant))      # prix en direct avant d'alerter
        for v in _dropped:
            ctx.state.setdefault("live_rejected", []).append(dedupe_key(v.offer))
    if instant:
        done = announce(instant, ctx.seen, "⚡ 10/10 : publication immédiate", ctx.dry, summary=False)
        publish(done, ctx.dry, "⚡ 10/10 immédiat")


def tick_slots(ctx: Ctx) -> None:
    """Publie le créneau de 12h / 19h s'il est dû : les meilleures offres de la réserve, revérifiées une dernière fois."""
    cfg, pub = ctx.cfg, ctx.cfg["publication"]
    sid = slots.due_slot(cfg, ctx.state.get("published", []), ctx.now_utc)
    ctx.stats["next_slot"] = slots.next_slot_label(cfg, ctx.now_utc)
    if not sid:
        return
    hhmm = sid.split("@")[1]
    label = f"Publication de {hhmm.replace(':00', 'h').replace(':', 'h')}"
    ctx.pool = poolmod.expire(ctx.pool, cfg, ctx.now_utc)
    entries = [(e["key"], poolmod.verdict_from_dict(e["verdict"])) for e in ctx.pool]
    valid = [(k, v) for k, v in entries if poolmod.still_valid(v, cfg, ctx.today)]
    fresh = fresh_candidates([v for _, v in valid], ctx.seen, cfg)
    std = [v for v in fresh if v.kind != "business_deal"]
    biz = [v for v in fresh if v.kind == "business_deal"]
    # dernière revérification : un prix vu ce matin peut avoir disparu depuis
    std_ok = verify.verify_all(std, cfg, ctx.token, ctx.today)
    biz_ok = verify.verify_all(biz, cfg, ctx.token, ctx.today)
    spare = cfg.get("live", {}).get("spare_candidates", 3)
    cand_std = select_top(std_ok, cfg, pub["per_slot"]["standard"] + spare)
    cand_biz = select_top(biz_ok, cfg, pub["per_slot"]["business"] + spare)
    # prix EN DIRECT des finalistes (des remplaçants prennent la place de ceux qui échouent)
    fin_std, drop_std = verify.live_confirm(cand_std, cfg, ctx.today, pub["per_slot"]["standard"])
    fin_biz, drop_biz = verify.live_confirm(cand_biz, cfg, ctx.today, pub["per_slot"]["business"])
    live_dropped = {id(v) for v in drop_std + drop_biz}
    top = fin_std + fin_biz
    n_std, n_biz = sum(v.kind != "business_deal" for v in top), sum(v.kind == "business_deal" for v in top)
    print(f"{label} ({sid}) : {len(std_ok)} standard et {len(biz_ok)} business confirmés en réserve -> "
          f"{n_std} + {n_biz} publiés")
    done = announce(top, ctx.seen, label, ctx.dry, summary=True)
    publish(done, ctx.dry, label)
    if ctx.dry:
        return
    # nettoyage : publiées + devenues invalides + non confirmées partent ; les autres restent pour le prochain créneau
    gone = {dedupe_key(v.offer) for v in done}
    gone |= {k for k, v in entries if not poolmod.still_valid(v, cfg, ctx.today)}
    checked = std[: cfg["verification"]["max_checks"]] + biz[: cfg["verification"]["max_checks"]]
    ok_ids = {id(v) for v in std_ok + biz_ok}
    gone |= {dedupe_key(v.offer) for v in checked if id(v) not in ok_ids}
    gone |= {dedupe_key(v.offer) for v in drop_std + drop_biz}
    ctx.pool = [e for e in ctx.pool if e["key"] not in gone]
    ctx.state.setdefault("published", []).append(sid)
    ctx.state["last_slot"] = {"id": sid, "label": label, "at": ctx.now_iso, "standard": n_std, "business": n_biz,
                              "waiting_after": len(ctx.pool)}


def write_status(ctx: Ctx, source: str) -> None:
    """docs/status.json : permet de voir sur le téléphone si l'appli tourne, et pourquoi il n'y a (peut-être) rien à publier."""
    if ctx.dry:
        return
    st = _load(STATUS, {})
    st.update({"updated": ctx.now_iso, "source": source, "waiting": len(ctx.pool),
               "next_slot": ctx.stats.get("next_slot", slots.next_slot_label(ctx.cfg, ctx.now_utc)),
               "last_slot": ctx.state.get("last_slot"), "errors": ctx.errors[-3:], "ok": not ctx.errors})
    from . import live as livemod
    st["live_used"], st["live_budget"] = livemod.used(ctx.now_utc), ctx.cfg.get("live", {}).get("monthly_budget", 0)
    st["live_active"] = livemod.can_spend(ctx.cfg, ctx.now_utc)
    for k in ("offers", "candidates", "verified", "instant"):
        if k in ctx.stats:
            st[k] = ctx.stats[k]
    st[f"last_{source}"] = ctx.now_iso
    _save(STATUS, st)


def run(demo: bool, dry: bool, now_utc: Optional[datetime] = None) -> int:
    ctx = Ctx(dry or demo, now_utc)
    cfg, today = ctx.cfg, ctx.today
    budgets = evaluate.load_budgets()
    history = _load(HISTORY, {})

    offers = []
    try:
        if demo:
            offers = providers.demo_offers(today)
        else:
            if ctx.token:
                offers += providers.travelpayouts(cfg["origins"], months_ahead(cfg["months_ahead"], today), ctx.token)
            else:
                print("[travelpayouts] TRAVELPAYOUTS_TOKEN absent : source ignorée")
            offers += providers.rss(cfg["rss_feeds"])
    except Exception:
        traceback.print_exc()
        ctx.errors.append("collecte des prix : erreur inattendue (voir le journal du scan)")
    print(f"{len(offers)} offres collectées")
    ctx.stats["offers"] = len(offers)
    if ctx.token and not demo and len(offers) == 0:
        ctx.errors.append("aucune offre collectée : l'API de prix ne répond pas ou le token est refusé")

    try:
        unknown: dict = {}
        for o in offers:
            if o.dest not in DESTINATIONS and o.source == "travelpayouts":
                unknown[o.dest] = min(unknown.get(o.dest, 1e9), o.price_eur)
        if unknown:
            best = sorted(unknown.items(), key=lambda kv: kv[1])[:15]
            print("destinations absentes de la base (prix mini) : " + ", ".join(f"{c} {p:.0f}€" for c, p in best))

        verdicts = [v for o in offers if (v := evaluate.evaluate(o, cfg, history, budgets, today))]
        biz_verdicts = [v for o in offers if (v := evaluate.evaluate_business(o, cfg, budgets, today))]
        if evaluate.NEAR_MISSES:
            near = sorted(evaluate.NEAR_MISSES, reverse=True)[:5]
            print(f"{len(evaluate.NEAR_MISSES)} offres sous le seuil ({cfg['publication']['min_score']}/10) ; les 5 meilleures :")
            for sc_, d in near:
                print(f"  {sc_}/11  {d}")
        if not demo and offers:
            evaluate.update_history(history, offers)          # après l'évaluation : on compare à l'historique passé

        if demo:
            dispatch(verdicts + biz_verdicts, {}, cfg, True, 6)
            return 0
        ingest(ctx, verdicts + biz_verdicts)
        tick_slots(ctx)
    except Exception:
        traceback.print_exc()
        ctx.errors.append("analyse : erreur inattendue (voir le journal du scan)")
    finally:
        if not demo and not dry:
            if offers:
                _save(HISTORY, history)
            ctx.save()
            write_status(ctx, "scan")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="offres fictives, rien n'est écrit ni envoyé")
    ap.add_argument("--dry-run", action="store_true", help="vraies sources, mais aucune écriture ni envoi")
    a = ap.parse_args()
    sys.exit(run(a.demo, a.dry_run))
