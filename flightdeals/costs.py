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


def private_room_price(dorm: float, cfg: dict) -> float:
    """Chambre privée simple (guesthouse / hôtel économique) déduite du prix d'un lit en dortoir."""
    p = cfg["costs"]["private_room"]
    f = p["factor_cheap"] if dorm <= p["cheap_dorm_max"] else p["factor_mid"] if dorm <= p["mid_dorm_max"] else p["factor_high"]
    return dorm * f


def lodging_per_night(dorm: float, cfg: dict) -> tuple[float, str]:
    """Chambre privée par défaut ; auberge (dortoir) seulement si la chambre privée est vraiment chère."""
    p = cfg["costs"]["private_room"]
    if not p["enabled"]:
        return dorm, "auberge"
    room = private_room_price(dorm, cfg)
    if room > p["max_per_night"]:
        return dorm, "auberge (chambre privée trop chère)"
    return room, "chambre privée"


def mini_trips(days: int, cfg: dict) -> int:
    m = cfg["costs"]["mini_trip"]
    if days < m["min_stay_days"]:
        return 0
    return 2 if days >= m["second_trip_from_days"] else 1


def stay_cost(country_code: str, depart: date, ret: date, cfg: dict) -> dict:
    """Détail du séjour : chambre privée, repas, transports, activités, mini-trip(s) train/bus vers d'autres villes,
    visa, assurance, SIM, marge."""
    days = max((ret - depart).days, 1)
    c = _costs().get(country_code)
    cc = cfg["costs"]
    if not c:
        per = cc["default_per_day"]
        c = {"lodging": per * 0.4, "food": per * 0.3, "transport": per * 0.15, "activities": per * 0.15,
             "visa": 0, "intercity": 60, "visa_note": "pays non chiffré : estimation moyenne"}
    peak = _peak_days(depart, ret, cfg)
    night, ltype = lodging_per_night(c["lodging"], cfg)
    lodging = night * days + night * (cc["peak_lodging_multiplier"] - 1) * peak
    food = c["food"] * days
    transport = c["transport"] * days
    activities = c["activities"] * days
    n_trips = mini_trips(days, cfg)
    trip_cost = max(c["intercity"], cc["mini_trip"]["min_cost_eur"])
    intercity = trip_cost * n_trips
    insurance = cc["insurance_per_day"] * days
    subtotal = lodging + food + transport + activities + intercity + c["visa"] + insurance + cc["arrival_flat_eur"]
    buffer = subtotal * cc["buffer_pct"] / 100
    total = subtotal + buffer
    mt = cc["mini_trip"]
    lines = {f"Hébergement ({ltype}, {round(night)} €/nuit)": round(lodging), "Repas": round(food),
             "Transports locaux": round(transport), "Activités": round(activities)}
    if n_trips:
        lines[f"Mini-trip : train/bus A/R vers une autre ville ({n_trips} × {mt['days_each']} j)"] = round(intercity)
    lines.update({"Visa / autorisation": round(c["visa"]), "Assurance": round(insurance),
                  "Transferts + SIM": cc["arrival_flat_eur"], "Marge": round(buffer)})
    return {
        "days": days, "per_day": round(total / days, 1), "total": round(total), "lines": lines,
        "lodging_type": ltype, "lodging_night": round(night), "mini_trips": n_trips,
        "visa_note": c.get("visa_note", ""), "peak_days": peak,
    }
