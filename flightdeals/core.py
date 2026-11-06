"""Modèles, géographie et estimation de durée."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional


@dataclass
class Offer:
    origin: str                       # code aéroport d'origine (ex. CDG)
    dest: str                         # code destination (aéroport ou ville)
    price_eur: float                  # prix A/R TTC
    cabin: str = "economy"            # economy | business
    depart: Optional[date] = None
    return_date: Optional[date] = None
    transfers: int = 0
    airline: str = ""
    duration_min: Optional[int] = None  # durée aller (minutes), si fournie
    link: str = ""
    source: str = ""
    title: str = ""
    flagged_error: bool = False       # la source parle d'erreur de prix


@dataclass
class Verdict:
    kind: str                         # error_fare | deal | business_deal
    offer: Offer
    dest_city: str
    country: str
    distance_km: int
    flight_hours: float
    stay_days: int
    daily_budget: float
    stay_cost: float
    trip_total: float
    discount_pct: Optional[int]       # vs médiane historique de la route
    aircraft: str                     # widebody_confirmed | widebody_probable | unverified | not_required
    aircraft_note: str
    reasons: list = field(default_factory=list)
    itinerary: list = field(default_factory=list)   # lignes détaillées (montages d'escales)
    baseline_eur: Optional[float] = None
    saving_pct: Optional[int] = None
    score: float = 0.0                              # note sur 11
    score_parts: dict = field(default_factory=dict)
    score_line: str = ""
    issue: Optional[int] = None                    # numéro de l'Issue GitHub (pour les refus)

    def to_dict(self) -> dict:
        d = asdict(self)
        o = d["offer"]
        o["depart"] = o["depart"].isoformat() if o["depart"] else None
        o["return_date"] = o["return_date"].isoformat() if o["return_date"] else None
        return d


@dataclass
class Leg:
    """Un billet aller simple (un tronçon)."""
    orig: str
    dest: str
    dep: datetime                     # heure locale de départ, avec fuseau
    dur_min: int
    price: float
    airline: str = ""
    link: str = ""
    transfers: int = 0

    @property
    def dep_utc(self) -> datetime:
        d = self.dep if self.dep.tzinfo else self.dep.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)

    @property
    def arr_utc(self) -> datetime:
        return self.dep_utc + timedelta(minutes=self.dur_min)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def estimate_hours(distance_km: float, transfers: int = 0, duration_min: Optional[int] = None) -> float:
    """Durée aller en heures. Utilise la durée de l'API si dispo, sinon estimation."""
    if duration_min:
        return duration_min / 60
    return distance_km / 850 + 0.75 + 2.5 * transfers
