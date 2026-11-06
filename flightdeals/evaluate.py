"""Décide si une offre est une erreur de prix / très bonne affaire."""
from __future__ import annotations

import json
import statistics
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from . import aircraft, preferences, scoring
from .airports import DESTINATIONS, ORIGINS, secrecy
from .core import Offer, Verdict, estimate_hours, haversine_km

ROOT = Path(__file__).resolve().parent.parent


def load_budgets() -> dict:
    return json.loads((ROOT / "data" / "budgets.json").read_text(encoding="utf-8"))


NEAR_MISSES: list = []      # (note, description) des meilleures offres refusées, pour régler le seuil


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
    if o.price_eur <= 0 or o.transfers > cfg.get("max_transfers", 2):
        return None

    # Fenêtre de départ : 6 mois max
    if o.depart:
        if o.depart < today or o.depart > today + timedelta(days=30 * cfg["months_ahead"]):
            return None

    city, cc, dlat, dlon, dest_airports = DESTINATIONS[o.dest]
    if cc in cfg.get("excluded_countries", []):
        return None
    _, olat, olon = ORIGINS[o.origin]
    km = haversine_km(olat, olon, dlat, dlon)
    hours = estimate_hours(km, o.transfers, o.duration_min)

    # Durée du séjour : plus la destination est loin, plus le séjour minimum est long (max 3 semaines)
    sd = cfg["stay_days"]
    lo = scoring.min_stay_for(km, cfg)
    if o.depart and o.return_date:
        stay = (o.return_date - o.depart).days
        if not lo <= stay <= sd["max"]:
            return None
    else:
        stay = scoring.default_stay(km, cfg)

    if preferences.violates(cfg, dest=o.dest, km=km, hours=hours, depart=o.depart, stay=stay):
        return None

    # Contrainte avion (au-delà de 5 h)
    status, note = aircraft.check_route(
        o.origin, dest_airports or [o.dest], o.transfers, hours,
        cfg["aircraft"]["long_haul_hours"], str(ROOT / "data" / "routes.dat"),
    )
    if status == "REJECT":
        return None
    if status == "unverified" and cfg["aircraft"]["strict"]:
        return None

    # Budget du séjour entier (backpacker éco) : vols + hébergement + nourriture + transports + activités
    daily = budgets.get(cc)
    if daily is None:
        return None
    eco = cfg["economy"]
    stay_cost = (daily * stay + eco["extras_flat_eur"]) * (1 + eco["buffer_pct"] / 100)
    total = o.price_eur + stay_cost
    if total > eco["total_trip_cap_eur"]:
        return None
    if eco.get("flight_cap_eur") and o.price_eur > eco["flight_cap_eur"]:
        return None

    if o.cabin == "business":
        b = cfg["business"]
        if not b["enabled"] or km < b["min_km"] or o.price_eur > b["flight_cap_eur"] or status == "not_required":
            return None

    prices = history.get(route_key(o), [])
    min_hist = cfg["anomaly"]["min_history"]
    hist_median = statistics.median(prices) if len(prices) >= min_hist else None
    hist_disc = (1 - o.price_eur / hist_median) if hist_median else None

    sc = scoring.score_deal(
        price=o.price_eur, km=km, cabin=o.cabin, total=total, stay=stay, stops=o.transfers,
        aircraft_status=status, secrecy=secrecy(o.dest), separate_tickets=False, cfg=cfg,
        hist_median=hist_median, hist_disc=hist_disc, flagged_error=o.flagged_error)
    if sc.total < cfg["scoring"]["min_score"]:
        NEAR_MISSES.append((sc.total, f"{o.origin}→{city} {o.price_eur:.0f}€ (séjour ~{total:.0f}€) : {sc.line()}"))
        return None

    kind = "business_deal" if o.cabin == "business" else ("error_fare" if sc.error_fare else "deal")
    reasons = [f"Note {sc.total}/11 (seuil {cfg['scoring']['min_score']})",
               f"Vol {o.price_eur:.0f} € ; séjour complet ≈ {total:.0f} € (budget max {eco['total_trip_cap_eur']} €)",
               f"−{sc.discount * 100:.0f} % vs prix habituel de la ligne" + (" (historique)" if hist_median else " (estimation selon la distance)")]
    if sc.error_fare:
        reasons.append("Erreur de prix probable")

    return Verdict(
        kind=kind, offer=o, dest_city=city, country=cc, distance_km=round(km),
        flight_hours=round(hours, 1), stay_days=stay, daily_budget=daily,
        stay_cost=round(stay_cost), trip_total=round(total),
        discount_pct=round(sc.discount * 100),
        aircraft=status, aircraft_note=note, reasons=reasons,
        score=sc.total, score_parts=sc.parts, score_line=sc.line(),
    )


def update_history(history: dict, offers: list[Offer], keep: int = 200) -> None:
    for o in offers:
        if o.source.startswith("rss"):
            continue  # les flux ne donnent pas un prix comparable (dates inconnues)
        lst = history.setdefault(route_key(o), [])
        lst.append(round(o.price_eur))
        del lst[:-keep]
