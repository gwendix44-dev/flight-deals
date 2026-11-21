"""État de publication : réserve, créneaux, 10/10 immédiats, bons plans, cooldown par destination."""
from __future__ import annotations

from datetime import datetime, timedelta

from .util import ROOT, now_utc, parse_dt, read_json, write_json

STATE = ROOT / "data" / "publish_state.json"
WATCH = ROOT / "data" / "watch.json"
DEALS = ROOT / "docs" / "deals.json"
EMPTY = {"slots_done": {}, "reserve": [], "published": [], "good": [], "instant_log": []}


def load_state() -> dict:
    s = read_json(STATE, {}) or {}
    for k, v in EMPTY.items():
        s.setdefault(k, type(v)())
    return s


def save_state(s: dict) -> None:
    done = s["slots_done"]
    for k in sorted(done)[:-12]:
        del done[k]
    s["instant_log"] = s["instant_log"][-40:]
    write_json(STATE, s)


def _age_h(iso, now):
    t = parse_dt(iso)
    return (now - t).total_seconds() / 3600 if t else 1e9


def purge(items: list, valid, now: datetime, max_hours: float, ts_key="found_at") -> list:
    return [d for d in items if _age_h(d.get(ts_key), now) <= max_hours and valid(d)]


def in_cooldown(deal: dict, published: list, cfg: dict, now: datetime) -> bool:
    """Même destination déjà publiée dans les 7 jours, sauf prix >= 25 % plus bas."""
    p = cfg["publication"]
    for old in published:
        if old["dest"] == deal["dest"] and (old["kind"] == "business") == (deal["kind"] == "business") and _age_h(old.get("published_at"), now) < p["destination_cooldown_days"] * 24:
            if deal["flight_price"] <= old["flight_price"] * (1 - p["cooldown_override_drop"]):
                continue
            return True
    return False


def pick(cands: list, n: int, cfg: dict, published: list, now: datetime) -> list:
    """À tour de rôle par région : max 2 par région, 1 par destination, jamais de remplissage."""
    maxr = cfg["publication"]["max_per_region"]
    pool = sorted((d for d in cands if not in_cooldown(d, published, cfg, now)), key=lambda d: -d["score"])
    by_region: dict[str, list] = {}
    for d in pool:
        by_region.setdefault(d["region"], []).append(d)
    chosen, dests, count = [], set(), {}
    progressed = True
    while len(chosen) < n and progressed:
        progressed = False
        for region in sorted(by_region, key=lambda r: -by_region[r][0]["score"] if by_region[r] else 0):
            lst = by_region[region]
            while lst and (lst[0]["dest"] in dests or count.get(region, 0) >= maxr):
                lst.pop(0)
            if lst and len(chosen) < n:
                d = lst.pop(0)
                chosen.append(d)
                dests.add(d["dest"])
                count[region] = count.get(region, 0) + 1
                progressed = True
    return chosen


def load_watch() -> dict:
    return read_json(WATCH, {}) or {}


def confirm_instant(deals: list, watch: dict, now: datetime, cfg: dict):
    """Un 10/10 doit être revu à un 2e scan >= 10 min plus tard au même prix ou moins cher."""
    gap = timedelta(minutes=cfg["publication"]["instant_min_gap_minutes"])
    ready, new_watch = [], {}
    for d in deals:
        prev = watch.get(d["key"])
        first = parse_dt(prev["first_seen"]) if prev else None
        if prev and first and now - first >= gap and d["flight_price"] <= prev["price"] * 1.0:
            ready.append(d)
        new_watch[d["key"]] = {"first_seen": prev["first_seen"] if prev else now.isoformat(),
                               "price": min(d["flight_price"], prev["price"]) if prev else d["flight_price"]}
    return ready, new_watch


def write_deals(state: dict, extras: dict, now: datetime, valid) -> dict:
    """docs/deals.json : ce que l'appli affiche. Pépites publiées < 48 h, bons plans < 36 h."""
    pub = purge(state["published"], valid, now, 48, "published_at")
    state["published"] = pub
    data = {
        "updated": now.isoformat(),
        "deals": [d for d in pub if d["kind"] != "business"],
        "business": [d for d in pub if d["kind"] == "business"],
        "good": purge(state["good"], valid, now, 36),
    }
    data.update(extras)
    write_json(DEALS, data)
    return data
