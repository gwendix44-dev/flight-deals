"""Décide si une offre est une erreur de prix / très bonne affaire."""
from __future__ import annotations

import json
import statistics
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from . import aircraft
from .airports import DESTINATIONS, ORIGINS
from .core import Offer, Verdict, estimate_hours, haversine_km

ROOT = Path(__file__).resolve().parent.parent


def load_budgets() -> dict:
    return json.loads((ROOT / "data" / "budgets.json").read_text(encoding="utf-8"))


def _tier(table: dict, km: float, up_key="up_to_km"):
    return table["short"] if km <= table[up_key] else table["long"]


def route_key(o: Offer) -> str:
    return f"{o.origin}-{o.dest}-{o.cabin}"


def median_discount(history: dict, o: Offer, min_history: int) -> Optional[float]:
    prices = history.get(route_key(o), [])
    if len(prices) < min_history:
        return None
    med = statistics.median(prices)
    return 1 - o.price_eur / med if med else None


def evaluate(o: Offer, cfg: dict, history: dict, budgets: dict, today: Optional[date] = None) -> Optional[Verdict]:
    today = today or date.today()
    if o.origin not in ORIGINS or o.dest not in DESTINATIONS:
        return None
    if o.price_eur <= 0:
        return None

    # Fenêtre de départ : 6 mois max
    if o.depart:
        if o.depart < today or o.depart > today + timedelta(days=30 * cfg["months_ahead"]):
            return None

    # Durée du séjour
    sd = cfg["stay_days"]
    if o.depart and o.return_date:
        stay = (o.return_date - o.depart).days
        if not sd["min"] <= stay <= sd["max"]:
            return None
    else:
        stay = sd["default_when_unknown"]

    city, cc, dlat, dlon, dest_airports = DESTINATIONS[o.dest]
    if cc in cfg.get("excluded_countries", []):
        return None
    _, olat, olon = ORIGINS[o.origin]
    km = haversine_km(olat, olon, dlat, dlon)
    hours = estimate_hours(km, o.transfers, o.duration_min)

    # Contrainte avion (au-delà de 5 h)
    status, note = aircraft.check_route(
        o.origin, dest_airports or [o.dest], o.transfers, hours,
        cfg["aircraft"]["long_haul_hours"], str(ROOT / "data" / "routes.dat"),
    )
    if status == "REJECT":
        return None
    if status == "unverified" and cfg["aircraft"]["strict"]:
        return None

    # Budget de séjour (backpacker éco)
    daily = budgets.get(cc)
    if daily is None:
        return None
    eco = cfg["economy"]
    stay_cost = (daily * stay + eco["extras_flat_eur"]) * (1 + eco["buffer_pct"] / 100)
    total = o.price_eur + stay_cost

    disc = median_discount(history, o, cfg["anomaly"]["min_history"])
    reasons: list[str] = []

    if o.cabin == "business":
        b = cfg["business"]
        if not b["enabled"] or km < b["min_km"] or o.price_eur > b["flight_cap_eur"]:
            return None
        if status == "not_required":
            return None  # court-courrier : pas pertinent
        reasons.append(f"Business A/R à {o.price_eur:.0f} € (plafond {b['flight_cap_eur']} €)")
        kind = "business_deal"
    else:
        flight_cap = _tier(eco["flight_cap_eur"], km)
        total_cap = _tier(eco["total_trip_cap_eur"], km)
        if o.price_eur > flight_cap or total > total_cap:
            return None
        reasons.append(f"Vol {o.price_eur:.0f} € ≤ plafond {flight_cap} € ; séjour complet ≈ {total:.0f} € ≤ {total_cap} €")
        kind = "deal"

    if o.flagged_error or (disc is not None and disc >= cfg["anomaly"]["error_fare_discount"]):
        kind = "error_fare" if o.cabin != "business" else kind
        reasons.append("Erreur de prix probable" + (f" (−{disc * 100:.0f} % vs médiane de la ligne)" if disc is not None else " (signalée par la source)"))
    elif disc is not None and disc >= cfg["anomaly"]["unusual_discount"]:
        reasons.append(f"Prix inhabituel : −{disc * 100:.0f} % vs médiane de la ligne")

    return Verdict(
        kind=kind, offer=o, dest_city=city, country=cc, distance_km=round(km),
        flight_hours=round(hours, 1), stay_days=stay, daily_budget=daily,
        stay_cost=round(stay_cost), trip_total=round(total),
        discount_pct=round(disc * 100) if disc is not None else None,
        aircraft=status, aircraft_note=note, reasons=reasons,
    )


def update_history(history: dict, offers: list[Offer], keep: int = 200) -> None:
    for o in offers:
        if o.source.startswith("rss"):
            continue  # les flux ne donnent pas un prix comparable (dates inconnues)
        lst = history.setdefault(route_key(o), [])
        lst.append(round(o.price_eur))
        del lst[:-keep]
