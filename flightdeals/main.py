"""Point d'entrée : python -m flightdeals.main [--demo] [--dry-run]"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import evaluate, notify, providers
from .core import Offer

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "history.json"
SEEN = ROOT / "data" / "seen.json"
DEALS = ROOT / "docs" / "deals.json"


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


def dedupe_key(o: Offer) -> str:
    raw = f"{o.origin}|{o.dest}|{o.cabin}|{o.depart}|{o.return_date}|{o.title}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def dispatch(candidates, seen: dict, cfg: dict, dry: bool, limit: int) -> list:
    """Garde les `limit` meilleures affaires nouvelles, envoie les alertes, et ne marque comme
    « déjà vues » que celles réellement alertées (un échec d'envoi ne doit pas les perdre)."""
    drop = 1 - cfg["realert_if_price_drops_pct"] / 100
    fresh = []
    for v in candidates:
        prev = seen.get(dedupe_key(v.offer))
        if prev is None or v.offer.price_eur <= prev * drop:
            fresh.append(v)
    # erreurs de prix d'abord, puis le meilleur rapport prix/distance
    fresh.sort(key=lambda v: (v.kind != "error_fare", v.offer.price_eur / max(v.distance_km, 1)))
    top = fresh[:limit]
    print(f"{len(candidates)} affaires, {len(fresh)} nouvelles, {len(top)} retenues pour alerte")
    if dry:
        for v in top:
            print("\n" + notify.body(v))
        return top
    sent = notify.create_issues(top)
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
    store["deals"] = ([dict(v.to_dict(), found_at=now, key=dedupe_key(v.offer)) for v in top] + old)[:200]
    _save(DEALS, store)


def run(demo: bool, dry: bool) -> int:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
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

    verdicts = [v for o in offers if (v := evaluate.evaluate(o, cfg, history, budgets, today))]
    if not demo:
        evaluate.update_history(history, offers)  # après l'évaluation : on compare à l'historique passé

    sent = dispatch(verdicts, seen, cfg, dry or demo, cfg["max_alerts_per_run"]["scan"])
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
