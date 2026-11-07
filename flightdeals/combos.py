"""Scan des montages d'escales : python -m flightdeals.combos [--dry-run]"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import evaluate, preferences, providers, scoring, stopovers
from .airports import DESTINATIONS, HUBS, ORIGINS
from .core import haversine_km
from .main import ROOT, Ctx, ingest, months_ahead, tick_slots, write_status


def _group(legs, keep: int = 6):
    g: dict = defaultdict(lambda: defaultdict(list))
    for l in legs:
        g[l.orig][l.dest].append(l)
    for o in g.values():
        for d, lst in o.items():
            lst.sort(key=lambda x: x.price)
            del lst[keep:]
    return g


def run(dry: bool, ctx: Ctx) -> int:
    cfg = ctx.cfg
    if not cfg["stopovers"]["enabled"]:
        return 0
    token = ctx.token
    if not token:
        print("[combos] TRAVELPAYOUTS_TOKEN absent : rien à faire")
        return 0
    today = ctx.today
    months = months_ahead(cfg["months_ahead"], today)
    budgets = evaluate.load_budgets()
    routes_path = str(ROOT / "data" / "routes.dat")

    # 1. Tronçons aller simple, directs : origines -> monde, hubs -> monde
    legs = []
    for src in dict.fromkeys([*ORIGINS, *HUBS]):   # LIS, MAD, DUB sont origines ET hubs : une seule requête
        legs += providers.oneway_legs(src, months, token, direct=True, unique=True)
    print(f"{len(legs)} tronçons collectés")
    legs_from = _group(legs)

    # 2. Prix de référence = meilleur A/R classique (avec ou sans escale) déjà proposé, par origine/destination
    base: dict = {}
    for o in providers.travelpayouts(list(ORIGINS), months, token):
        k = (o.origin, o.dest)
        base[k] = min(base.get(k, 1e9), o.price_eur)

    # 3. Aller en montage : on ne garde que les plus prometteurs, puis on cherche un retour pour chacun
    paths = stopovers.build_paths(legs_from, max_price=cfg["stopovers"]["max_outbound_eur"])
    paths = [p for p in paths if (p.legs[0].orig, p.legs[-1].dest) in base]
    paths.sort(key=lambda p: p.price / base[(p.legs[0].orig, p.legs[-1].dest)])
    print(f"{len(paths)} montages aller candidats")

    ret_cache: dict = {}

    def best_return(o, d, arr_date):
        _, olat, olon = ORIGINS[o]
        km = haversine_km(olat, olon, DESTINATIONS[d][2], DESTINATIONS[d][3])
        lo = arr_date + timedelta(days=scoring.min_stay_for(km, cfg))       # plus c'est loin, plus le séjour minimum est long
        hi = arr_date + timedelta(days=cfg["stay_days"]["max"])
        ms = sorted({f"{x.year}-{x.month:02d}" for x in (lo, hi)})
        best = None
        for m in ms:
            key = (d, o, m)
            if key not in ret_cache:
                ret_cache[key] = providers.oneway_legs(d, [m], token, destination=o, direct=False, unique=False, limit=60)
            for leg in ret_cache[key]:
                if lo <= leg.dep_utc.date() <= hi and (best is None or leg.price < best.price):
                    best = leg
        return best

    verdicts, checked = [], 0
    for p in paths:
        if checked >= cfg["stopovers"]["max_candidates_to_verify"]:
            break
        o, d = p.legs[0].orig, p.legs[-1].dest
        key = (o, d)
        if p.price >= base[key] * 0.8:      # l'aller seul dépasse déjà le gain attendu : inutile d'aller chercher un retour
            continue
        checked += 1
        ret = best_return(o, d, p.legs[-1].arr_utc.date())
        if not ret:
            continue
        v = stopovers.evaluate_combo(p, ret, base[key], cfg, budgets, routes_path, today)
        if v:
            verdicts.append(v)
    print(f"{checked} montages vérifiés, {len(verdicts)} retenus")

    ctx.stats["combos_checked"] = checked
    ingest(ctx, verdicts)          # mêmes règles que les autres offres : >= 8/10, revérification, 10/10 immédiat ou réserve
    tick_slots(ctx)
    return 0


def main(dry: bool) -> int:
    """Ne fait jamais échouer le workflow sur une erreur de données : l'erreur est notée dans docs/status.json."""
    ctx = Ctx(dry)
    try:
        run(dry, ctx)
    except Exception:
        traceback.print_exc()
        ctx.errors.append("montages d'escales : erreur inattendue (voir le journal du scan)")
    finally:
        ctx.save()
        write_status(ctx, "combos")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(main(ap.parse_args().dry_run))
