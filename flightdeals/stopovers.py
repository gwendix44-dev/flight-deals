"""Montages d'escales : combiner plusieurs billets aller simple pour battre le prix d'un billet classique.

Règles d'escale (hub) :
  * "short"    : entre 4 h et 10 h, sans chevaucher la nuit locale 00h-05h (pas de nuit à l'aéroport) ;
  * "stopover" : au moins 2 nuits sur place (mini-étape, hébergement compté dans le budget) ;
  * tout le reste est refusé (moins de 4 h = risque de rater la correspondance ; 10 h à 2 nuits = nuit à l'aéroport
    ou nuit unique mal exploitée).
Itinéraire : 2 escales maximum (3 tronçons).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from . import aircraft, costs as costcalc, preferences, scoring
from .airports import DESTINATIONS, HUBS, ORIGINS, SAME_CITY, airports_of, coords, secrecy
from .core import Leg, Verdict, Offer, estimate_hours, haversine_km

MIN_LAYOVER = timedelta(hours=4)
SHORT_MAX = timedelta(hours=10)
MIN_NIGHTS = 2
MIN_STOPOVER = timedelta(hours=40)


@dataclass
class Path:
    legs: list
    layovers: list = field(default_factory=list)   # (hub, kind, nights)

    @property
    def price(self) -> float:
        return sum(l.price for l in self.legs)


def classify_layover(arr_utc: datetime, hub_tz: float, next_dep: datetime):
    """-> ("short"|"stopover", nuits) ou None si refusé."""
    arr_local = (arr_utc + timedelta(hours=hub_tz)).replace(tzinfo=None)
    dep_local = next_dep.replace(tzinfo=None)        # l'heure de départ est déjà locale au hub
    dep_utc = next_dep if next_dep.tzinfo else next_dep.replace(tzinfo=timezone.utc)
    lay = dep_utc.astimezone(timezone.utc) - arr_utc
    if lay < MIN_LAYOVER:
        return None
    nights = (dep_local.date() - arr_local.date()).days
    if nights >= MIN_NIGHTS and lay >= MIN_STOPOVER:
        return "stopover", nights
    if lay <= SHORT_MAX:
        d = arr_local.date()
        while d <= dep_local.date():            # chevauche-t-on 00h-05h ?
            n0 = datetime.combine(d, time(0))
            if arr_local < n0 + timedelta(hours=5) and dep_local > n0:
                return None
            d += timedelta(days=1)
        return "short", nights
    return None


def _hub_ok(origin: str, hub: str) -> bool:
    return hub != origin and SAME_CITY.get(origin) != hub


def build_paths(legs_from: dict, max_price: float) -> list:
    """legs_from[orig][dest] -> [Leg...]. Retourne les trajets aller O -> hub(s) -> destination."""
    paths: list[Path] = []
    for o in ORIGINS:
        for h1, legs1 in legs_from.get(o, {}).items():
            if h1 not in HUBS or not _hub_ok(o, h1):
                continue
            tz1 = HUBS[h1][4]
            for l1 in legs1:
                if l1.price >= max_price:
                    continue
                for d, legs2 in legs_from.get(h1, {}).items():
                    for l2 in legs2:
                        if l1.price + l2.price > max_price:
                            continue
                        lay = classify_layover(l1.arr_utc, tz1, l2.dep)
                        if not lay:
                            continue
                        if d in DESTINATIONS:                       # 1 escale
                            paths.append(Path([l1, l2], [(h1, *lay)]))
                        elif d in HUBS and d != h1 and _hub_ok(o, d):  # 2 escales
                            tz2 = HUBS[d][4]
                            for d3, legs3 in legs_from.get(d, {}).items():
                                if d3 not in DESTINATIONS:
                                    continue
                                for l3 in legs3:
                                    if l1.price + l2.price + l3.price > max_price:
                                        continue
                                    lay2 = classify_layover(l2.arr_utc, tz2, l3.dep)
                                    if lay2:
                                        paths.append(Path([l1, l2, l3], [(h1, *lay), (d, *lay2)]))
    return paths


_RANK = {"not_required": 0, "widebody_probable": 1, "unverified": 2}


def evaluate_combo(path: Path, ret: Leg, baseline: Optional[float], cfg: dict, budgets: dict,
                   routes_path: str, today=None) -> Optional[Verdict]:
    """Évalue un aller (montage) + un retour. Retourne un Verdict 'stopover_deal' ou None."""
    first, last = path.legs[0], path.legs[-1]
    o, d = first.orig, last.dest
    city, cc, dlat, dlon, d_airports = DESTINATIONS[d]
    if cc in cfg.get("excluded_countries", []):
        return None
    if baseline is None:
        return None                                        # pas de prix de référence -> pas de comparaison possible
    eco, sc = cfg["economy"], cfg["stopovers"]

    # Fenêtre de 6 mois, séjour sur place
    today = today or datetime.now(timezone.utc).date()
    days_to_go = (first.dep_utc.date() - today).days
    if days_to_go < cfg["verification"]["min_notice_days"] or days_to_go > 30 * cfg["months_ahead"]:
        return None
    stay = (ret.dep_utc.date() - last.arr_utc.date()).days
    if ret.transfers > cfg.get("max_transfers", 2):
        return None

    _, olat, olon = ORIGINS[o]
    km = haversine_km(olat, olon, dlat, dlon)
    if not scoring.min_stay_for(km, cfg) <= stay <= cfg["stay_days"]["max"]:
        return None
    if preferences.violates(cfg, dest=d, km=km, hours=sum(l.dur_min for l in path.legs) / 60,
                            depart=first.dep_utc.date(), stay=stay):
        return None
    flights = path.price + ret.price
    if eco.get("flight_cap_eur") and flights > eco["flight_cap_eur"]:
        return None
    saving = 1 - flights / baseline
    if saving < sc["min_saving"]:
        return None

    # Avion : chaque tronçon de plus de 5 h doit être en double couloir
    worst, notes = "not_required", []
    for leg in [*path.legs, ret]:
        a = coords(leg.orig); b = coords(leg.dest)
        hours = leg.dur_min / 60 if leg.dur_min else estimate_hours(haversine_km(*a, *b))
        st, note = aircraft.check_route(airports_of(leg.orig), airports_of(leg.dest), leg.transfers, hours,
                                        cfg["aircraft"]["long_haul_hours"], routes_path)
        if st == "REJECT" or (st == "unverified" and cfg["aircraft"]["strict"]):
            return None
        if _RANK.get(st, 0) > _RANK[worst]:
            worst = st
        if st in ("unverified", "widebody_probable"):
            notes.append(f"{leg.orig}→{leg.dest} : {note}")

    bd = costcalc.stay_breakdown(budgets, cc, stay, last.arr_utc.date(), cfg)
    if bd is None:
        return None
    stay_cost, cost_lines = bd
    daily = costcalc.daily(budgets, cc)
    stop_cost = 0.0
    for hub, kind, nights in path.layovers:
        if kind == "stopover":
            hub_cost = (costcalc.daily(budgets, HUBS[hub][1]) or 50) * nights * (1 + eco["buffer_pct"] / 100)
            stop_cost += hub_cost
            cost_lines.append((f"Mini-étape {nights} nuits à {HUBS[hub][0]}", round(hub_cost)))
    total = flights + stay_cost + stop_cost
    cap = scoring.total_cap(km, cfg)
    if total > cap:
        return None
    stops = len(path.layovers) + sum(l.transfers for l in path.legs)
    sc = scoring.score_deal(price=flights, km=km, cabin="economy", total=total, stay=stay, stops=stops,
                            aircraft_status=worst, secrecy=secrecy(d), separate_tickets=True, cfg=cfg)
    if sc.total < cfg["scoring"]["min_score"]:
        return None

    itin = []
    for leg in path.legs:
        itin.append(f"✈ {leg.orig}→{leg.dest} le {leg.dep:%d/%m %H:%M} · {leg.price:.0f} € {leg.airline} {leg.link}".rstrip())
    for i, (hub, kind, nights) in enumerate(path.layovers):
        txt = (f"mini-étape de {nights} nuits à {HUBS[hub][0]} (hébergement et repas inclus dans le budget)"
               if kind == "stopover" else f"escale de jour à {HUBS[hub][0]} (4-10 h, sans nuit à l'aéroport)")
        itin.insert(2 * i + 1, f"   ↳ {txt}")
    itin.append(f"✈ Retour {ret.orig}→{ret.dest} le {ret.dep:%d/%m %H:%M} · {ret.price:.0f} € {ret.airline} {ret.link}".rstrip())

    reasons = [f"Note {sc.total}/11 (seuil {cfg['scoring']['min_score']})",
               f"−{saving * 100:.0f} % vs le meilleur billet classique trouvé ({baseline:.0f} €)",
               f"Vols {flights:.0f} € ; séjour complet ≈ {total:.0f} € (budget max {cap:.0f} € pour {km:.0f} km)"]
    offer = Offer(origin=o, dest=d, price_eur=round(flights), depart=first.dep_utc.date(),
                  return_date=ret.dep_utc.date(), transfers=stops, source="combo-escales",
                  link=first.link, title=" > ".join([o] + [h for h, _, _ in path.layovers] + [d]))
    return Verdict(kind="stopover_deal", offer=offer, dest_city=city, country=cc, distance_km=round(km),
                   flight_hours=round(sum(l.dur_min for l in path.legs) / 60, 1), stay_days=stay,
                   daily_budget=daily, cost_lines=cost_lines, stay_cost=round(stay_cost + stop_cost), trip_total=round(total),
                   discount_pct=None, aircraft=worst, aircraft_note=" | ".join(notes), reasons=reasons,
                   itinerary=itin, baseline_eur=baseline, saving_pct=round(saving * 100),
                   score=sc.total, score_parts=sc.parts, score_line=sc.line(), legs=[*path.legs, ret])
