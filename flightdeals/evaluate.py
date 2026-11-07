"""Décide si une offre est une erreur de prix / très bonne affaire."""
from __future__ import annotations

import json
import statistics
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from . import aircraft, costs as costcalc, preferences, scoring
from .airports import DESTINATIONS, ORIGINS, secrecy
from .core import Offer, Verdict, estimate_hours, haversine_km

ROOT = Path(__file__).resolve().parent.parent


def load_budgets() -> dict:
    """Barème de coûts par pays (data/costs.json)."""
    return costcalc.load_costs()


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
    if o.origin not in ORIGINS or o.dest not in DESTINATIONS or o.cabin == "business":
        return None          # le business class a sa propre section (evaluate_business)
    ver = cfg["verification"]
    if o.price_eur < ver["min_plausible_price_eur"] and not o.flagged_error:
        return None          # prix A/R irréaliste (taxes comprises) : donnée douteuse
    if o.transfers > cfg.get("max_transfers", 2):
        return None

    # Fenêtre de départ : 6 mois max
    if o.depart:
        if o.depart < today + timedelta(days=ver["min_notice_days"]) or o.depart > today + timedelta(days=30 * cfg["months_ahead"]):
            return None      # trop proche pour réserver sereinement (visa, congés) ou au-delà de 6 mois

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
    bd = costcalc.stay_breakdown(budgets, cc, stay, o.depart, cfg, origin=o.origin)
    if bd is None:
        return None
    stay_cost, cost_lines = bd
    daily = costcalc.daily(budgets, cc)
    eco = cfg["economy"]
    total = o.price_eur + stay_cost
    cap = scoring.total_cap(km, cfg)
    if total > cap:
        return None
    if eco.get("flight_cap_eur") and o.price_eur > eco["flight_cap_eur"]:
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

    if cfg["scoring"].get("require_anomaly") and not sc.error_fare:
        # Un bon prix ne suffit pas : l'appli cherche une pépite rare, pas un voyage correct qui te ferait partir
        # juste avant une vraie occasion.
        NEAR_MISSES.append((sc.total - 0.05, f"{o.origin}→{city} {o.price_eur:.0f}€ : bon deal ({sc.total}/11) mais PAS une anomalie de prix"))
        return None
    kind = "error_fare" if sc.error_fare else "deal"
    reasons = [f"Note {sc.total}/11 (seuil {cfg['scoring']['min_score']})",
               f"Vol {o.price_eur:.0f} € ; séjour complet ≈ {total:.0f} € (budget max {cap:.0f} € pour {km:.0f} km)",
               f"−{sc.discount * 100:.0f} % vs prix habituel de la ligne" + (" (historique)" if hist_median else " (estimation selon la distance)")]
    if sc.error_fare:
        reasons.append("Erreur de prix probable")
    if hist_median:
        cheaper = sum(1 for x in prices if x > o.price_eur)
        reasons.append(f"Moins cher que {round(100 * cheaper / len(prices))} % des {len(prices)} prix observés sur cette ligne")

    return Verdict(
        kind=kind, offer=o, dest_city=city, country=cc, distance_km=round(km),
        flight_hours=round(hours, 1), stay_days=stay, daily_budget=daily,
        stay_cost=round(stay_cost), trip_total=round(total),
        discount_pct=round(sc.discount * 100),
        aircraft=status, aircraft_note=note, reasons=reasons,
        score=sc.total, score_parts=sc.parts, score_line=sc.line(), cost_lines=cost_lines,
    )


def evaluate_business(o: Offer, cfg: dict, budgets: dict, today: Optional[date] = None) -> Optional[Verdict]:
    """Section business class : A/R <= 800 € sur un long-courrier, SANS tenir compte du prix du séjour.

    Pas de note sur 11, pas de budget total ni de durée de séjour imposés : seuls comptent le prix, la remise par rapport au
    prix habituel du business sur cette distance, l'avion (double couloir au-delà de 5 h), les dates et tes préférences.
    Le coût d'un séjour n'est affiché qu'à titre indicatif."""
    today = today or date.today()
    b = cfg["business"]
    if not b["enabled"] or o.cabin != "business" or o.origin not in ORIGINS or o.dest not in DESTINATIONS:
        return None
    if o.price_eur > b["flight_cap_eur"] or (o.price_eur < b["min_plausible_eur"] and not o.flagged_error):
        return None
    if o.transfers > cfg.get("max_transfers", 2):
        return None
    ver = cfg["verification"]
    if o.depart and (o.depart < today + timedelta(days=ver["min_notice_days"])
                     or o.depart > today + timedelta(days=30 * cfg["months_ahead"])):
        return None
    city, cc, dlat, dlon, dest_airports = DESTINATIONS[o.dest]
    if cc in cfg.get("excluded_countries", []):
        return None
    _, olat, olon = ORIGINS[o.origin]
    km = haversine_km(olat, olon, dlat, dlon)
    if km < b["min_km"]:
        return None                                   # court-courrier : pas un « bon deal business »
    hours = estimate_hours(km, o.transfers, o.duration_min)
    stay = scoring.default_stay(km, cfg)
    if preferences.violates(cfg, dest=o.dest, km=km, hours=hours, depart=o.depart, stay=stay):
        return None
    status, anote = aircraft.check_route(o.origin, dest_airports or [o.dest], o.transfers, hours,
                                         cfg["aircraft"]["long_haul_hours"], str(ROOT / "data" / "routes.dat"))
    if status == "REJECT" or (status == "unverified" and cfg["aircraft"]["strict"]):
        return None
    ref = scoring.reference_price(km, "business", cfg)
    disc = 1 - o.price_eur / ref
    if disc < b["min_discount"] and not o.flagged_error:
        return None
    # Note /11 : 11 x remise / 0,85 (plafonnée). 8/10 correspond à ~62 % de remise, 10/10 à ~77 %.
    note = min(11.0, 11 * max(disc, 0) / b["note_full_discount"]) + (1.0 if o.flagged_error else 0.0)
    note = round(min(note, 11.0), 1)
    if note < cfg["publication"]["min_score"]:
        NEAR_MISSES.append((note, f"business {o.origin}→{city} {o.price_eur:.0f}€ : remise {disc * 100:.0f} % → note {note}/11"))
        return None
    bd = costcalc.stay_breakdown(budgets, cc, stay, o.depart, cfg, origin=o.origin)
    stay_cost, lines = bd if bd else (0, [])
    reasons = [f"Note {note}/11 : business A/R {o.price_eur:.0f} € (plafond {b['flight_cap_eur']} €), −{disc * 100:.0f} % vs prix habituel "
               f"(~{ref:.0f} € sur {km:.0f} km)",
               "Le prix du séjour n'est pas pris en compte dans cette sélection (indicatif seulement)"]
    if o.flagged_error:
        reasons.append("Erreur de prix probable (signalée par la source)")
    return Verdict(kind="business_deal", offer=o, dest_city=city, country=cc, distance_km=round(km),
                   flight_hours=round(hours, 1), stay_days=stay, daily_budget=costcalc.daily(budgets, cc) or 0,
                   stay_cost=round(stay_cost), trip_total=round(o.price_eur + stay_cost), discount_pct=round(disc * 100),
                   aircraft=status, aircraft_note=anote, reasons=reasons, cost_lines=lines, score=note,
                   score_line=f"remise {disc * 100:.0f} % vs prix habituel du business (~{ref:.0f} €) · note {note}/11")


def update_history(history: dict, offers: list[Offer], keep: int = 200) -> None:
    for o in offers:
        if o.source.startswith("rss"):
            continue  # les flux ne donnent pas un prix comparable (dates inconnues)
        lst = history.setdefault(route_key(o), [])
        lst.append(round(o.price_eur))
        del lst[:-keep]
