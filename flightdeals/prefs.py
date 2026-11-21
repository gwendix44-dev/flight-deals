"""Préférences apprises des refus. Elles ne font que DURCIR la configuration."""
from __future__ import annotations

import copy

from .util import ROOT, read_json, write_json

PATH = ROOT / "docs" / "preferences.json"

DEFAULT = {
    "total_cap_eur": None, "cap_by_tier": {}, "business_cap_eur": None, "min_stay_extra": 0,
    "max_stay_days": None, "max_distance_km": None, "min_distance_km": None, "max_flight_hours": None,
    "max_transfers": None, "strict_aircraft": False, "stopovers_disabled": False,
    "excluded_destinations": [], "excluded_countries": [], "excluded_months": [], "min_secrecy": None,
    "min_score_bonus": 0.0, "refused_issues": [], "refused_keys": [],
}


def load(path=None) -> dict:
    p = read_json(path or PATH, {}) or {}
    out = copy.deepcopy(DEFAULT)
    out.update({k: v for k, v in p.items() if k in DEFAULT})
    return out


def save(p: dict, path=None) -> None:
    write_json(path or PATH, p)


def effective(cfg: dict, p: dict) -> dict:
    """Configuration durcie par les préférences. Ne relâche JAMAIS un critère."""
    c = copy.deepcopy(cfg)
    if p.get("max_transfers") is not None:
        c["max_transfers"] = min(c["max_transfers"], int(p["max_transfers"]))
    if p.get("max_stay_days"):
        c["stay"]["max_days"] = min(c["stay"]["max_days"], int(p["max_stay_days"]))
    extra = int(p.get("min_stay_extra") or 0)
    if extra:
        c["stay"]["min_by_distance_km"] = [[lim, d + extra] for lim, d in c["stay"]["min_by_distance_km"]]
    table = [list(x) for x in c["budget_by_distance_km"]]
    if p.get("total_cap_eur"):
        table = [[lim, min(cap, p["total_cap_eur"])] for lim, cap in table]
    for idx, cap in (p.get("cap_by_tier") or {}).items():
        i = int(idx)
        if 0 <= i < len(table):
            table[i][1] = min(table[i][1], cap)
    c["budget_by_distance_km"] = table
    if p.get("business_cap_eur"):
        c["business"]["max_price_eur"] = min(c["business"]["max_price_eur"], p["business_cap_eur"])
    c["aircraft"]["strict"] = bool(c["aircraft"]["strict"] or p.get("strict_aircraft"))
    c["stopovers"]["enabled"] = bool(c["stopovers"]["enabled"] and not p.get("stopovers_disabled"))
    c["excluded_countries"] = sorted(set(c["excluded_countries"]) | set(p.get("excluded_countries") or []))
    c["excluded_destinations"] = sorted(set(p.get("excluded_destinations") or []))
    c["excluded_months"] = sorted(set(p.get("excluded_months") or []))
    c["max_distance_km"] = p.get("max_distance_km")
    c["min_distance_km"] = p.get("min_distance_km")
    c["max_flight_hours"] = p.get("max_flight_hours")
    c["min_secrecy"] = p.get("min_secrecy")
    c["scoring"]["publish"] = c["scoring"]["publish"] + min(float(p.get("min_score_bonus") or 0), 1.0)
    return c


def describe(p: dict) -> list[str]:
    """Phrases lisibles de ce que l'appli a appris (affichées dans le dashboard et pour /prefs)."""
    out = []
    if p.get("strict_aircraft"):
        out.append("Mode avion strict : seuls les gros-porteurs confirmés passent (rejette presque tous les vols avec escale).")
    for i, cap in (p.get("cap_by_tier") or {}).items():
        out.append(f"Budget total plafonné à {cap} € (palier de distance n°{int(i) + 1}).")
    if p.get("total_cap_eur"):
        out.append(f"Budget total plafonné à {p['total_cap_eur']} € partout.")
    if p.get("business_cap_eur"):
        out.append(f"Business plafonné à {p['business_cap_eur']} €.")
    if p.get("min_stay_extra"):
        out.append(f"Séjour minimum +{p['min_stay_extra']} jours.")
    if p.get("max_stay_days"):
        out.append(f"Séjour limité à {p['max_stay_days']} jours.")
    if p.get("max_distance_km"):
        out.append(f"Distance maximale {p['max_distance_km']} km.")
    if p.get("min_distance_km"):
        out.append(f"Distance minimale {p['min_distance_km']} km.")
    if p.get("max_transfers") is not None:
        out.append(f"{p['max_transfers']} escale(s) maximum.")
    if p.get("stopovers_disabled"):
        out.append("Montages à billets séparés désactivés.")
    if p.get("excluded_destinations"):
        out.append("Destinations exclues : " + ", ".join(p["excluded_destinations"]) + ".")
    if p.get("excluded_countries"):
        out.append("Pays exclus : " + ", ".join(p["excluded_countries"]) + ".")
    if p.get("excluded_months"):
        out.append("Mois de départ exclus : " + ", ".join(map(str, p["excluded_months"])) + ".")
    if p.get("min_secrecy"):
        out.append("Destinations plus rares exigées.")
    if p.get("min_score_bonus"):
        out.append(f"Seuil de publication relevé de {p['min_score_bonus']}.")
    return out
