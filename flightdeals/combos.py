"""Montages d'escales (billets séparés) : origine -> hub -> destination, avec escale courte (4-10 h, jamais de nuit
à l'aéroport) ou longue (>= 2 nuits). Doit battre le meilleur billet classique A/R d'au moins 20 %."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .model import Offer
from .world import coords, dest_code, world


def local_hour_overlap_night(start_utc: datetime, end_utc: datetime, utc_off: int, cfg: dict) -> bool:
    """Vrai si l'attente à l'aéroport du hub traverse la fenêtre 00h-05h (heure locale)."""
    s = cfg["stopovers"]
    t = start_utc + timedelta(hours=utc_off)
    end = end_utc + timedelta(hours=utc_off)
    while t < end:
        if s["night_start"] <= t.hour < s["night_end"]:
            return True
        t += timedelta(minutes=30)
    return False


def layover_ok(arrive_utc: datetime, depart_utc: datetime, utc_off: int, cfg: dict):
    """-> 'short' | 'long' | None"""
    s = cfg["stopovers"]
    h = (depart_utc - arrive_utc).total_seconds() / 3600
    if h >= s["long_min_h"]:
        return "long"
    if s["short_min_h"] <= h <= s["short_max_h"] and not local_hour_overlap_night(arrive_utc, depart_utc, utc_off, cfg):
        return "short"
    return None


def build_combos(leg1: list[dict], leg2: list[dict], hub_code: str, origin: str, back_price, classic_best: dict,
                 cfg: dict, today) -> list[Offer]:
    """leg1 : origine->hub (dicts de fetch_oneways) ; leg2 : hub->destinations.
    back_price : fonction(dest) -> prix du retour simple dest->origine ou None.
    classic_best : {(origine, dest): meilleur prix A/R classique bagages compris}."""
    hub = world()["hubs"][hub_code]
    s = cfg["stopovers"]
    out: list[Offer] = []
    for a in leg1:
        arr = a["dep"] + timedelta(minutes=a["dur_min"] or 120)
        if a["price"] > s["max_outbound_eur"]:
            continue
        for b in leg2:
            dest = dest_code(b["dest"])
            if not dest:
                continue
            kind = layover_ok(arr.astimezone(timezone.utc), b["dep"].astimezone(timezone.utc), hub["utc"], cfg)
            if not kind:
                continue
            back = back_price(dest)
            ref = classic_best.get((origin, dest))
            if back is None or ref is None:
                continue
            total = a["price"] + b["price"] + back
            if total > ref * (1 - s["min_saving"]):
                continue
            ret_days = cfg["stay"]["max_days"]
            dep_date = a["dep"].date()
            out.append(Offer(
                origin=origin, dest=dest, price=round(total), depart=dep_date,
                return_date=dep_date + timedelta(days=min(14, ret_days)), transfers=1, airline=a["airline"],
                source="combo", link=a["link"],
                stopover={"hub": hub_code, "hub_city": hub["city"], "kind": kind, "leg1": round(a["price"]),
                          "leg2": round(b["price"]), "back": round(back), "classic": round(ref),
                          "warning": "Billets séparés : aucune protection en cas de retard ou de correspondance ratée, "
                                     "bagages à ré-enregistrer, visas de transit à vérifier."}))
    return out
