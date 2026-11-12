"""Réserve d'offres : les deals ≥ 8/10 trouvés et vérifiés dans la journée attendent ici leur créneau de publication."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from . import preferences, scoring
from .common import ROOT, _load, _save, dedupe_key
from .core import Leg, Offer, Verdict

POOL = ROOT / "data" / "pool.json"
STATE = ROOT / "data" / "publish_state.json"
WATCH = ROOT / "data" / "watch.json"            # bons plans 7-8/10 vus récemment (dashboard, sans alerte)


def verdict_to_dict(v: Verdict) -> dict:
    d = v.to_dict()
    d["legs"] = [{"orig": l.orig, "dest": l.dest, "dep": l.dep.isoformat(), "dur_min": l.dur_min, "price": l.price,
                  "airline": l.airline, "link": l.link, "transfers": l.transfers} for l in v.legs]
    return d


def verdict_from_dict(d: dict) -> Verdict:
    d = dict(d)
    o = dict(d.pop("offer"))
    o["depart"] = date.fromisoformat(o["depart"]) if o.get("depart") else None
    o["return_date"] = date.fromisoformat(o["return_date"]) if o.get("return_date") else None
    legs = [Leg(l["orig"], l["dest"], datetime.fromisoformat(l["dep"]), l["dur_min"], l["price"], l["airline"],
                l["link"], l["transfers"]) for l in d.pop("legs", [])]
    d["cost_lines"] = [tuple(x) for x in d.get("cost_lines", [])]
    return Verdict(offer=Offer(**o), legs=legs, **d)


def load_pool() -> list:
    return _load(POOL, [])


def save_pool(pool: list) -> None:
    _save(POOL, pool[-200:])


def load_watch() -> list:
    return _load(WATCH, [])


def save_watch(watch: list) -> None:
    watch.sort(key=lambda e: -e["verdict"].get("score", 0))
    _save(WATCH, watch[:80])                       # les 80 meilleurs bons plans récents


def add(pool: list, v: Verdict, now_iso: str) -> bool:
    """Ajoute (ou améliore) une offre. Retourne True si la réserve a changé."""
    key = dedupe_key(v.offer)
    for e in pool:
        if e["key"] == key:
            if v.offer.price_eur < e["verdict"]["offer"]["price_eur"]:
                e.update(found_at=now_iso, verdict=verdict_to_dict(v))
                return True
            return False
    pool.append({"key": key, "found_at": now_iso, "verdict": verdict_to_dict(v)})
    return True


def waiting_keys(pool: list) -> dict:
    return {e["key"]: e["verdict"]["offer"]["price_eur"] for e in pool}


def still_valid(v: Verdict, cfg: dict, today: date, min_score: float | None = None) -> bool:
    """Une offre en attente reste publiable si ses dates, tes préférences et ton budget l'acceptent encore."""
    o = v.offer
    if v.country in cfg.get("excluded_countries", []):
        return False
    if o.depart and o.depart < today + timedelta(days=cfg["verification"]["min_notice_days"]):
        return False
    if preferences.violates(cfg, dest=o.dest, km=v.distance_km, hours=v.flight_hours, depart=o.depart, stay=v.stay_days):
        return False
    floor = cfg["publication"]["min_score"] if min_score is None else min_score
    if v.score < floor + cfg.get("score_bonus_from_prefs", 0):
        return False
    if v.kind == "business_deal":
        return o.price_eur <= cfg["business"]["flight_cap_eur"]
    return v.trip_total <= scoring.total_cap(v.distance_km, cfg)


def expire(pool: list, cfg: dict, now: Optional[datetime] = None, hours: Optional[float] = None) -> list:
    now = now or datetime.now(timezone.utc)
    max_age = timedelta(hours=hours if hours is not None else cfg["publication"]["pool_max_age_hours"])
    keep = []
    for e in pool:
        try:
            if now - datetime.fromisoformat(e["found_at"]) <= max_age:
                keep.append(e)
        except (KeyError, ValueError):
            pass
    return keep
