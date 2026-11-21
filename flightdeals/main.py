"""Un scan complet : collecte -> évaluation -> revérification -> réserve -> 10/10 -> créneau 12h/19h."""
from __future__ import annotations

import os
import sys
import traceback
from collections import Counter
from datetime import date, datetime, timedelta

from . import github, history as H, notify, prefs as P, publish as PB, slots, sources
from .evaluate import evaluate
from .util import ROOT, months_ahead, now_utc, paris_now, read_json, write_json

STATUS = ROOT / "docs" / "status.json"


def load_config() -> dict:
    return read_json(ROOT / "config.json")


def make_valid(cfg: dict, prefs: dict, today: date):
    refused = set(prefs.get("refused_keys") or [])

    def valid(d: dict) -> bool:
        if d["key"] in refused or d["dest"] in cfg["excluded_destinations"]:
            return False
        try:
            dep = date.fromisoformat(d["depart"])
        except (KeyError, ValueError):
            return False
        return dep >= today + timedelta(days=cfg["min_notice_days"])
    return valid


def verify_price(deal: dict, token: str, cfg: dict, fetch=None):
    """-> ('ok', prix) | ('gone', None) | ('pricey', prix) | ('skip', None) | ('error', None)."""
    if deal.get("dates_unconfirmed") or deal["kind"] == "combo" or not token:
        return "skip", None
    from .world import dest_airports
    try:
        p = sources.exact_price(deal["origin"], dest_airports(deal["dest"]), date.fromisoformat(deal["depart"]),
                                date.fromisoformat(deal["return"]), token, fetch=fetch)
    except Exception:
        return "error", None
    if p is None:
        return "gone", None
    if p > deal["price"] * (1 + cfg["price_tolerance"]):
        return "pricey", p
    return "ok", p


def evaluate_all(offers, cfg, prefs, hist, today):
    rejects, evaluated = Counter(), []
    best: dict[str, dict] = {}
    for o in offers:
        deal, why = evaluate(o, cfg, prefs, hist, today)
        if why:
            rejects[why] += 1
            continue
        evaluated.append(deal)
        cur = best.get(deal["key"])
        if not cur or deal["score"] > cur["score"] or (deal["score"] == cur["score"] and deal["price"] < cur["price"]):
            best[deal["key"]] = deal
    return list(best.values()), rejects


def run_scan(now=None, token=None, push=None, issue=None, fetch=None, rss=None, errors=None, cfg=None, prefs=None, write=True):
    now = now or now_utc()
    today = paris_now(now).date()
    errors = errors if errors is not None else []
    base = cfg or load_config()
    prefs = prefs if prefs is not None else P.load()
    cfg = P.effective(base, prefs)
    valid = make_valid(cfg, prefs, today)
    push = push or notify.send_push
    issue = issue or github.create_issue
    pubcfg = cfg["publication"]

    state = PB.load_state()
    hist = H.load()
    state["reserve"] = PB.purge(state["reserve"], valid, now, pubcfg["reserve_hours"])
    state["good"] = PB.purge(state["good"], valid, now, pubcfg["reserve_hours"])

    offers = []
    if token:
        offers += sources.fetch_roundtrips(cfg["origins"], months_ahead(today, cfg["months_ahead"]), token, errors, fetch=fetch)
    else:
        errors.append("TRAVELPAYOUTS_TOKEN absent : aucune source de prix principale")
    offers += sources.fetch_rss(cfg["rss_feeds"], errors, get=rss)

    deals, rejects = evaluate_all(offers, cfg, prefs, hist, today)
    H.update(hist, offers, today)
    pubs = cfg["scoring"]["publish"]
    cands = sorted([d for d in deals if d["score"] >= pubs], key=lambda d: -d["score"])
    goods = [d for d in deals if cfg["scoring"]["good_deal"] <= d["score"] < pubs and d["kind"] != "business"]
    missed = sorted([d for d in deals if d["score"] < pubs], key=lambda d: -d["score"])[:3]

    # Revérification pour les dates exactes (au plus 25 appels)
    verified, checks = [], 0
    for d in cands:
        if checks >= 25:
            break
        st, p = verify_price(d, token, cfg, fetch=fetch)
        if st in ("ok", "gone", "pricey", "error"):
            checks += 1
        if st in ("gone", "pricey", "error"):
            rejects["prix disparu ou +10 % à la revérification" if st != "error" else "revérification impossible"] += 1
            continue
        d["verified"] = ("Prix revérifié pour ces dates exactes (cache)" if st == "ok" else
                         "À confirmer sur le lien de l'offre" if d.get("dates_unconfirmed") else "Prix du cache, à confirmer")
        d["found_at"] = now.isoformat()
        verified.append(d)

    # Réserve (fusion par clé)
    reserve = {d["key"]: d for d in state["reserve"]}
    for d in verified:
        old = reserve.get(d["key"])
        if old and old["flight_price"] <= d["flight_price"]:
            continue
        reserve[d["key"]] = d
    state["reserve"] = list(reserve.values())
    gmap = {d["key"]: d for d in state["good"]}
    for d in goods:
        d["found_at"] = now.isoformat()
        gmap[d["key"]] = d
    state["good"] = list(gmap.values())

    # 10/10 : double observation >= 10 min, plafonds 3 par scan et 4 par jour
    tens = [d for d in verified if d["score"] >= cfg["scoring"]["instant"]]
    watch = PB.load_watch()
    ready, new_watch = PB.confirm_instant(tens, watch, now, cfg)
    sent_today = sum(1 for t in state["instant_log"] if t[:10] == today.isoformat())
    n_instant = 0
    for d in sorted(ready, key=lambda x: -x["score"]):
        if n_instant >= pubcfg["instant_per_scan"] or sent_today + n_instant >= pubcfg["instant_per_day"]:
            break
        if PB.in_cooldown(d, state["published"], cfg, now):
            continue
        d["instant"] = True
        d["published_at"] = now.isoformat()
        d["issue"] = issue(d)
        state["published"].append(d)
        state["reserve"] = [r for r in state["reserve"] if r["key"] != d["key"]]
        push(f"🚨 10/10 : {d['origin_city']} → {d['dest_city']} {d['price']} €", f"Note {d['score']}/11 · {d['depart']} → {d['return']}. Vérifie avant d'acheter.", tag="instant")
        state["instant_log"].append(now.isoformat())
        n_instant += 1
    if write:
        write_json(PB.WATCH, new_watch)

    # Créneau 12h / 19h
    last_slot = state.get("last_slot")
    due = slots.due_slot(now, state["slots_done"], cfg)
    if due:
        sid, at = due
        res = _publish_slot(state, cfg, sid, at, now, token, valid, push, issue, fetch)
        last_slot = res
        state["last_slot"] = res
        state["slots_done"][sid] = now.isoformat()
        if not res["standard"] and not res["business"]:
            res["best_missed"] = [_line(m) for m in missed]
    state["last_slot"] = last_slot
    nxt = slots.next_slot(now, cfg)
    status = {
        "ok": not any(e.startswith("TRAVELPAYOUTS") for e in errors) and bool(offers), "updated": now.isoformat(),
        "last_scan": now.isoformat(), "offers": len(offers), "candidates": len(cands), "verified": len(verified),
        "waiting": len(state["reserve"]), "instant": n_instant, "errors": errors[:8],
        "next_slot": nxt[2] if nxt else "", "last_slot": last_slot, "best_missed": [_line(m) for m in missed],
        "rejections": rejects.most_common(8), "prefs": P.describe(prefs), "source": "scan",
    }
    if write:
        _save(state, hist, status, now, valid)
    return state, status


def _line(d):
    parts = " · ".join(f"{k} {v[0]}/{v[1]}" for k, v in d.get("detail", {}).items())
    return f"{d['score']}/11 {d['origin']}→{d['dest']} {d['flight_price']}€ avec bagages (séjour ~{d['stay']['total']}€)" + (f" : {parts}" if parts else "")


def _publish_slot(state, cfg, sid, at, now, token, valid, push, issue, fetch):
    pubcfg = cfg["publication"]
    label = "Publication de " + at.astimezone(paris_now(now).tzinfo).strftime("%Hh")
    res_items = PB.purge(state["reserve"], valid, now, pubcfg["reserve_hours"])
    ok, checks = [], 0
    for d in sorted(res_items, key=lambda x: -x["score"]):
        if checks < 25:
            st, p = verify_price(d, token, cfg, fetch=fetch)
            checks += st in ("ok", "gone", "pricey", "error")
            if st in ("gone", "pricey"):
                continue
        ok.append(d)
    std = PB.pick([d for d in ok if d["kind"] != "business"], pubcfg["per_slot_standard"], cfg, state["published"], now)
    biz = PB.pick([d for d in ok if d["kind"] == "business"], pubcfg["per_slot_business"], cfg, state["published"], now)
    for d in std + biz:
        d["published_at"] = now.isoformat()
        d["slot"] = sid
        d["issue"] = issue(d)
        state["published"].append(d)
    keys = {d["key"] for d in std + biz}
    state["reserve"] = [d for d in ok if d["key"] not in keys]
    # bons plans : dashboard seulement, 1 par région, 4 max
    seen_regions, good = set(), []
    for d in sorted(state["good"], key=lambda x: -x["score"]):
        if d["region"] not in seen_regions and d["key"] not in keys and len(good) < pubcfg["good_deals_per_slot"]:
            good.append(d)
            seen_regions.add(d["region"])
    state["good"] = good
    title, body = notify.slot_message(label, std, biz)
    push(title, body, tag="slot-" + sid)
    return {"id": sid, "label": label, "at": now.isoformat(), "standard": len(std), "business": len(biz),
            "bons_plans": len(good), "waiting_after": len(state["reserve"])}


def _save(state, hist, status, now, valid):
    PB.save_state(state)
    H.save(hist)
    write_json(STATUS, status)
    PB.write_deals(state, {}, now, valid)


def main() -> int:
    errors: list[str] = []
    try:
        run_scan(token=os.environ.get("TRAVELPAYOUTS_TOKEN", "").strip(), errors=errors)
    except Exception as e:  # le workflow ne plante jamais : l'erreur s'affiche en rouge dans l'appli
        traceback.print_exc()
        old = read_json(STATUS, {}) or {}
        old.update({"ok": False, "updated": now_utc().isoformat(), "errors": [f"{type(e).__name__}: {str(e)[:200]}"] + errors})
        write_json(STATUS, old)
    return 0


if __name__ == "__main__":
    sys.exit(main())
