"""Point d'entrée : python -m flightdeals.main [--demo] [--dry-run]"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import evaluate, notify, preferences, providers
from .core import Offer

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "history.json"
SEEN = ROOT / "data" / "seen.json"
DEALS = ROOT / "docs" / "deals.json"
ALERTS = ROOT / "data" / "alerts_log.json"      # journal des pépites envoyées


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def months_ahead(n: int, today: date) -> list[str]:
    out, y, m = [], today.year, today.month
    for _ in range(n + 1):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


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


def dedupe_key(o: Offer) -> str:
    raw = f"{o.origin}|{o.dest}|{o.cabin}|{o.depart}|{o.return_date}|{o.title}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def dispatch(candidates, seen: dict, cfg: dict, dry: bool, limit: int, verifier=None) -> list:
    """Garde les `limit` meilleures affaires nouvelles, envoie les alertes, et ne marque comme
    « déjà vues » que celles réellement alertées (un échec d'envoi ne doit pas les perdre)."""
    drop = 1 - cfg["realert_if_price_drops_pct"] / 100
    fresh = []
    for v in candidates:
        prev = seen.get(dedupe_key(v.offer))
        if prev is None or v.offer.price_eur <= prev * drop:
            fresh.append(v)
    # meilleure note d'abord ; le business (sans note) se classe au prix du vol
    fresh.sort(key=lambda v: (-v.score, v.offer.price_eur if v.kind == "business_deal" else v.trip_total))
    if verifier:
        fresh = verifier(fresh)        # revérification : seules les offres confirmées continuent
    # Toute la planète : on prend à tour de rôle la meilleure offre de chaque région du monde (Asie, Amérique du Nord,
    # Amérique latine, Afrique, Océanie, Moyen-Orient), au plus N par région et une seule par destination.
    from .airports import region_of
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
    print(f"{len(candidates)} affaires, {len(fresh)} nouvelles, {len(top)} retenues pour alerte")
    if dry:
        for v in top:
            print("\n" + notify.body(v))
        return top
    n_year = alerts_last_year()
    for i, v in enumerate(top):
        v.reasons.append(f"Pépite n°{n_year + i + 1} sur les 12 derniers mois (objectif : 3 à 5 par an)")
    sent = notify.create_issues(top)
    log = _load(ALERTS, [])
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for v in sent:
        log.append({"at": now_iso, "route": f"{v.offer.origin}-{v.offer.dest}", "price": v.offer.price_eur, "kind": v.kind})
    if sent:
        _save(ALERTS, log[-200:])
    for v in sent:
        k = dedupe_key(v.offer)
        seen[k] = min(v.offer.price_eur, seen.get(k, 1e9))
    print(f"{len(sent)} alerte(s) envoyée(s)")
    return top      # le dashboard affiche les retenues, même si l'envoi a échoué


def publish(top: list, dry: bool) -> None:
    """Met à jour le dashboard (docs/deals.json), sans doublons."""
    if dry or not top:
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store = _load(DEALS, {"deals": []})
    keys = {dedupe_key(v.offer) for v in top}
    old = [d for d in store.get("deals", []) if d.get("key") not in keys]
    store["updated"] = now
    store["pepites_12m"] = alerts_last_year()
    store["deals"] = ([dict(v.to_dict(), found_at=now, key=dedupe_key(v.offer)) for v in top] + old)[:200]
    _save(DEALS, store)


def run(demo: bool, dry: bool) -> int:
    cfg = preferences.load_cfg()      # config.json + préférences apprises de tes refus
    today = date.today()
    budgets = evaluate.load_budgets()
    history = _load(HISTORY, {})
    seen = _load(SEEN, {})

    if demo:
        offers = providers.demo_offers(today)
    else:
        offers = []
        token = os.environ.get("TRAVELPAYOUTS_TOKEN")
        if token:
            offers += providers.travelpayouts(cfg["origins"], months_ahead(cfg["months_ahead"], today), token)
        else:
            print("[travelpayouts] TRAVELPAYOUTS_TOKEN absent : source ignorée")
        offers += providers.rss(cfg["rss_feeds"])
    print(f"{len(offers)} offres collectées")

    from .airports import DESTINATIONS
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
        top = sorted(evaluate.NEAR_MISSES, reverse=True)[:5]
        print(f"{len(evaluate.NEAR_MISSES)} offres sous le seuil ; les 5 meilleures :")
        for sc_, d in top:
            print(f"  {sc_}/11  {d}")
    if not demo:
        evaluate.update_history(history, offers)  # après l'évaluation : on compare à l'historique passé

    from . import verify
    token = os.environ.get("TRAVELPAYOUTS_TOKEN")
    verifier = None if demo else (lambda lst: verify.verify_all(lst, cfg, token, today))
    sent = dispatch(verdicts, seen, cfg, dry or demo, cfg["max_alerts_per_run"]["scan"], verifier)
    sent += dispatch(biz_verdicts, seen, cfg, dry or demo, cfg["max_alerts_per_run"]["business"], verifier)   # section business, à part
    if demo:
        return 0
    publish(sent, dry)

    if not dry:
        _save(HISTORY, history)
        _save(SEEN, dict(list(seen.items())[-5000:]))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="offres fictives, rien n'est écrit ni envoyé")
    ap.add_argument("--dry-run", action="store_true", help="vraies sources, mais aucune écriture ni envoi")
    a = ap.parse_args()
    sys.exit(run(a.demo, a.dry_run))
