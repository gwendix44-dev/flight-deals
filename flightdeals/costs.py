"""Coût réel du séjour (poste par poste) et trajet jusqu'à l'aéroport de départ."""
from __future__ import annotations

from datetime import date

from .util import ROOT, read_json
from .world import city


def _costs():
    return read_json(ROOT / "data" / "costs.json", {})


def positioning(origin: str, cfg: dict) -> float:
    if origin in cfg["home_airports"]:
        return 0.0
    return float(cfg["positioning_eur"].get(origin, cfg["positioning_default_eur"]))


def _peak_days(depart: date, ret: date, cfg: dict) -> int:
    c = cfg["costs"]
    ps, pe = c["peak_start"], c["peak_end"]
    n, d = 0, depart
    from datetime import timedelta
    while d < ret:
        md = d.strftime("%m-%d")
        if md >= ps or md <= pe:
            n += 1
        d += timedelta(days=1)
    return n


def stay_cost(country_code: str, depart: date, ret: date, cfg: dict) -> dict:
    """Détail du séjour : hébergement, repas, transports, activités, déplacements, visa, assurance, SIM, marge."""
    days = max((ret - depart).days, 1)
    c = _costs().get(country_code)
    cc = cfg["costs"]
    if not c:
        per = cc["default_per_day"]
        c = {"lodging": per * 0.4, "food": per * 0.3, "transport": per * 0.15, "activities": per * 0.15,
             "visa": 0, "intercity": 60, "visa_note": "pays non chiffré : estimation moyenne"}
    peak = _peak_days(depart, ret, cfg)
    lodging = c["lodging"] * days + c["lodging"] * (cc["peak_lodging_multiplier"] - 1) * peak
    food = c["food"] * days
    transport = c["transport"] * days
    activities = c["activities"] * days
    intercity = c["intercity"] * min(days / 14, 1.5)
    insurance = cc["insurance_per_day"] * days
    subtotal = lodging + food + transport + activities + intercity + c["visa"] + insurance + cc["arrival_flat_eur"]
    buffer = subtotal * cc["buffer_pct"] / 100
    total = subtotal + buffer
    return {
        "days": days, "per_day": round(total / days, 1), "total": round(total),
        "lines": {"Hébergement": round(lodging), "Repas": round(food), "Transports locaux": round(transport),
                  "Activités": round(activities), "Déplacements entre villes": round(intercity),
                  "Visa / autorisation": round(c["visa"]), "Assurance": round(insurance),
                  "Transferts + SIM": cc["arrival_flat_eur"], "Marge": round(buffer)},
        "visa_note": c.get("visa_note", ""), "peak_days": peak,
    }
