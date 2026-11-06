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

    drop = 1 - cfg["realert_if_price_drops_pct"] / 100
    new = []
    for v in verdicts:
        k = dedupe_key(v.offer)
        prev = seen.get(k)
        if prev is None or v.offer.price_eur <= prev * drop:
            new.append(v)
        seen[k] = min(v.offer.price_eur, prev) if prev else v.offer.price_eur
    new.sort(key=lambda v: (v.kind != "error_fare", v.trip_total))
    print(f"{len(verdicts)} affaires, {len(new)} nouvelles")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store = _load(DEALS, {"deals": []})
    store["updated"] = now
    store["deals"] = ([dict(v.to_dict(), found_at=now) for v in new] + store.get("deals", []))[:200]

    if dry or demo:
        for v in new:
            print("\n" + notify.body(v))
        if demo:
            return 0
    else:
        notify.create_issues(new)

    if not dry:
        _save(DEALS, store)
        _save(HISTORY, history)
        _save(SEEN, dict(list(seen.items())[-5000:]))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="offres fictives, rien n'est écrit ni envoyé")
    ap.add_argument("--dry-run", action="store_true", help="vraies sources, mais aucune écriture ni envoi")
    a = ap.parse_args()
    sys.exit(run(a.demo, a.dry_run))
