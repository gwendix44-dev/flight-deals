"""Scan des montages d'escales (toutes les 3 h) : ajoute les meilleurs à la réserve de publication."""
from __future__ import annotations

import os
import sys
import traceback

from . import combos as C, prefs as P, publish as PB, sources
from .baggage import baggage_for
from .evaluate import evaluate
from .main import STATUS, load_config, make_valid
from .util import months_ahead, now_utc, paris_now, read_json, write_json
from .world import dest_airports, world


def run(token, fetch=None, now=None, write=True):
    now = now or now_utc()
    today = paris_now(now).date()
    prefs = P.load()
    cfg = P.effective(load_config(), prefs)
    if not cfg["stopovers"]["enabled"] or not token:
        return []
    months = months_ahead(today, 4)
    errs: list = []
    hist = read_json(PB.ROOT / "data" / "history.json", {}) or {}
    classic: dict = {}
    for o in sources.fetch_roundtrips(cfg["home_airports"], months, token, errs, fetch=fetch):
        sur = baggage_for(o.airline, cfg)["surcharge"]
        k = (o.origin, o.dest)
        classic[k] = min(classic.get(k, 1e9), o.price + sur)
    w = world()
    lookups = {"n": 0}
    cache: dict = {}
    found = []
    for origin in cfg["home_airports"]:
        for hub in cfg["stopovers"]["hubs"]:
            if w["same_city"].get(origin) == hub or hub == origin:
                continue
            hub_ap = w["hubs"][hub]["airports"][0]
            leg1 = sources.fetch_oneways(origin, token, months, destination=hub_ap, direct=True, unique=False, limit=200, fetch=fetch)
            if not leg1:
                continue
            leg2 = sources.fetch_oneways(hub_ap, token, months, direct=False, unique=True, limit=1000, fetch=fetch)

            def back_price(dest, origin=origin):
                k = (dest, origin)
                if k not in cache:
                    if lookups["n"] >= cfg["stopovers"]["max_candidates"]:
                        return None
                    lookups["n"] += 1
                    rows = [r for ap in dest_airports(dest) for r in
                            sources.fetch_oneways(ap, token, months, destination=origin, direct=False, unique=True, fetch=fetch)]
                    cache[k] = min((r["price"] for r in rows), default=None)
                return cache[k]
            found += C.build_combos(leg1, leg2, hub, origin, back_price, classic, cfg, today)
    valid = make_valid(cfg, prefs, today)
    state = PB.load_state()
    reserve = {d["key"]: d for d in state["reserve"]}
    added = 0
    for o in found:
        deal, why = evaluate(o, cfg, prefs, hist, today)
        if deal and deal["score"] >= cfg["scoring"]["publish"]:
            deal["kind"] = "combo"
            deal["found_at"] = now.isoformat()
            deal["verified"] = "Billets séparés : à vérifier un par un"
            if deal["key"] not in reserve:
                added += 1
            reserve[deal["key"]] = deal
    state["reserve"] = PB.purge(list(reserve.values()), valid, now, cfg["publication"]["reserve_hours"])
    if write:
        PB.save_state(state)
        st = read_json(STATUS, {}) or {}
        st["last_combos"] = now.isoformat()
        write_json(STATUS, st)
    return found


def main() -> int:
    try:
        run(os.environ.get("TRAVELPAYOUTS_TOKEN", "").strip())
    except Exception:
        traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
