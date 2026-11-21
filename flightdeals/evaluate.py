"""Règles dures puis note. `evaluate` renvoie (deal|None, raison_du_rejet|None)."""
from __future__ import annotations

from datetime import date, timedelta

from . import aircraft, scoring
from .baggage import baggage_for
from .costs import positioning, stay_cost
from .links import google_flights_url
from .model import Offer
from .util import tier, tier_index
from .world import city, country, dest_airports, distance_km, region_of, world


def _min_stay(cfg, km):
    return tier(cfg["stay"]["min_by_distance_km"], km)


def evaluate(o: Offer, cfg: dict, prefs: dict, history: dict, today: date):
    """cfg = configuration déjà durcie par les préférences."""
    w = world()
    okey = o.key  # clé calculée AVANT toute date par défaut : stable pour les refus
    if o.dest not in w["destinations"]:
        return None, "destination inconnue"
    cc = country(o.dest)
    if cc in cfg["excluded_countries"]:
        return None, "pays exclu (Europe / Afrique du Nord / refus)"
    if o.dest in cfg["excluded_destinations"]:
        return None, "destination refusée"
    if okey in set(prefs.get("refused_keys") or []):
        return None, "offre refusée"
    km = distance_km(o.origin, o.dest)
    if not km:
        return None, "distance inconnue"
    if cfg["max_distance_km"] and km > cfg["max_distance_km"]:
        return None, "trop loin (préférence apprise)"
    if cfg["min_distance_km"] and km < cfg["min_distance_km"]:
        return None, "trop proche (préférence apprise)"
    if o.transfers > cfg["max_transfers"]:
        return None, "trop d'escales"
    if cfg["min_secrecy"] and scoring.secrecy(o.dest) < cfg["min_secrecy"]:
        return None, "destination trop touristique (préférence apprise)"

    dated = o.depart is not None and o.return_date is not None
    if dated:
        if o.depart < today + timedelta(days=cfg["min_notice_days"]):
            return None, "départ dans moins de 10 jours"
        if o.depart > today + timedelta(days=31 * cfg["months_ahead"]):
            return None, "départ au-delà de 6 mois"
        if o.depart.month in cfg["excluded_months"]:
            return None, "mois de départ exclu"
        stay_days = (o.return_date - o.depart).days
    else:
        stay_days = _min_stay(cfg, km) + 2  # offre de flux sans dates : séjour type, à confirmer
        o.depart = today + timedelta(days=45)
        o.return_date = o.depart + timedelta(days=stay_days)
    smin = _min_stay(cfg, km)
    if stay_days < smin:
        return None, "séjour trop court pour la distance"
    if stay_days > cfg["stay"]["max_days"]:
        return None, "séjour au-delà de 3 semaines"

    business = o.cabin == "business"
    bcfg = cfg["business"]
    floor = bcfg["min_plausible_eur"] if business else cfg["min_plausible_eur"]
    if o.price < floor and not o.flagged_error:
        return None, "prix aberrant (donnée douteuse)"

    airports = dest_airports(o.dest)
    status, anote = aircraft.check(o.origin, airports, km, o.transfers, cfg)
    if o.stopover:
        status, anote = "unverified", "Tronçons en billets séparés : avion à vérifier."
    if status == "reject":
        return None, "avion monocouloir au-delà de 5 h"
    hours = aircraft.flight_hours(km, cfg, o.transfers)
    if cfg["max_flight_hours"] and hours > cfg["max_flight_hours"]:
        return None, "vol trop long (préférence apprise)"
    if cfg["aircraft"]["strict"] and status == "unverified":
        return None, "mode avion strict : gros-porteur non confirmé"

    bag = baggage_for(o.airline, cfg, o.cabin)
    flight_price = o.price + bag["surcharge"]
    pos = positioning(o.origin, cfg)
    st = stay_cost(cc, o.depart, o.return_date, cfg)
    stay_total = st["total"]
    total = flight_price + stay_total + pos
    cap = tier(cfg["budget_by_distance_km"], km)

    base = {
        "key": okey, "kind": "business" if business else ("combo" if o.stopover else "standard"),
        "origin": o.origin, "origin_city": city(o.origin), "dest": o.dest, "dest_city": city(o.dest),
        "country": cc, "region": region_of(cc), "km": km, "price": round(o.price), "flight_price": round(flight_price),
        "transfers": o.transfers, "airline": bag["airline"], "airline_code": o.airline,
        "depart": o.depart.isoformat(), "return": o.return_date.isoformat(), "stay_days": stay_days,
        "dates_unconfirmed": not dated, "source": o.source, "title": o.title, "flagged_error": o.flagged_error,
        "baggage": bag, "aircraft": {"status": status, "note": anote}, "positioning": round(pos),
        "stay": st, "total": round(total), "cap": cap, "stopover": o.stopover,
        "hours": round(hours, 1),
        "links": {"verify": google_flights_url(o, airports), "airline": bag["site"], "offer": o.link},
    }
    if business:
        if km < bcfg["min_km"]:
            return None, "business : distance trop courte"
        if o.price > bcfg["max_price_eur"]:
            return None, "business : au-dessus du plafond"
        sc = scoring.score_business(price=o.price, km=km, flagged_error=o.flagged_error, cfg=cfg)
        if sc["discount"] < bcfg["min_discount"]:
            return None, "business : remise insuffisante"
        base.update(sc)
        base["total"] = round(o.price)  # séjour non pris en compte (indicatif)
        base["stay_indicative"] = stay_total
        return base, None

    if total > cap:
        return None, "budget total dépassé"
    med = scoring.hist_median(history, o.origin, o.dest)
    sc = scoring.score_standard(
        price=flight_price, km=km, total=total, cap=cap, stay_days=stay_days, stay_min=smin, stay_cost=stay_total,
        dest=o.dest, transfers=o.transfers, aircraft_status=status, separate_tickets=bool(o.stopover),
        flagged_error=o.flagged_error, med=med, cfg=cfg)
    base.update(sc)
    return base, None
