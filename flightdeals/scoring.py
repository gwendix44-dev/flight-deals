"""Grille d'évaluation d'un deal : note sur 11 (10 points + 1 point de bonus).

  Prix du vol vs prix habituel de la ligne ........ 0 à 3
  Budget total du séjour (vols + sur place) ........ 0 à 2
  Destination hors sentiers battus ................ 0 à 1,5
  Qualité du vol (escales, avion) ................. 0 à 1,5
  Durée de séjour adaptée à la distance ........... 0 à 1
  Coût par jour de voyage ......................... 0 à 1
  Bonus : erreur de prix avérée ................... 0 ou 1
Un deal n'est retenu que si la note atteint `scoring.min_score` (9,5 par défaut).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def min_stay_for(km: float, cfg: dict) -> int:
    """Séjour minimum selon la distance : plus c'est loin, plus c'est long."""
    for upto, days in cfg["stay_days"]["min_by_distance_km"]:
        if km <= upto:
            return days
    return cfg["stay_days"]["min_by_distance_km"][-1][1]


def default_stay(km: float, cfg: dict) -> int:
    """Durée supposée quand la source ne donne pas les dates."""
    return min(min_stay_for(km, cfg) + 3, cfg["stay_days"]["max"])


def reference_price(km: float, cabin: str, cfg: dict) -> float:
    """Prix A/R « habituel » estimé à partir de la distance (sert quand l'historique est trop court)."""
    b = cfg["scoring"]["benchmark"]
    eco = b["base"] + b["per_km"] * km
    return eco * (b["business_multiplier"] if cabin == "business" else 1.0)


@dataclass
class Score:
    total: float
    parts: dict = field(default_factory=dict)
    discount: float = 0.0          # remise vs prix habituel
    error_fare: bool = False

    def line(self) -> str:
        p = self.parts
        txt = (f"prix {p['prix']}/3 · budget {p['budget']}/2 · destination {p['destination']}/1,5 · "
               f"vol {p['vol']}/1,5 · durée {p['duree']}/1 · valeur/jour {p['valeur']}/1")
        return txt + (f" · bonus erreur de prix +{p['bonus']}" if p["bonus"] else "")


def score_deal(*, price: float, km: float, cabin: str, total: float, stay: int, stops: int,
               aircraft_status: str, secrecy: float, separate_tickets: bool, cfg: dict,
               hist_median: Optional[float] = None, hist_disc: Optional[float] = None,
               flagged_error: bool = False) -> Score:
    sc = cfg["scoring"]
    ref = hist_median or reference_price(km, cabin, cfg)
    disc = 1 - price / ref if ref else 0.0

    prix = 3 * clamp((disc - sc["price_disc_zero"]) / (sc["price_disc_full"] - sc["price_disc_zero"]))
    cap = cfg["economy"]["total_trip_cap_eur"]
    budget = 2 * clamp((cap - total) / (cap - sc["budget_full_eur"]))
    dest = secrecy
    vol = {0: 0.8, 1: 0.5, 2: 0.2}.get(stops, 0.0)
    vol += 0.2 if aircraft_status == "unverified" else 0.7
    if separate_tickets:
        vol -= 0.2
    vol = max(0.0, min(1.5, vol))
    lo = min_stay_for(km, cfg)
    duree = 1.0 if lo <= stay <= lo + cfg["stay_days"]["ideal_window_days"] else 0.6
    per_day = total / max(stay, 1)
    valeur = clamp((sc["value_zero_per_day"] - per_day) / (sc["value_zero_per_day"] - sc["value_full_per_day"]))

    error = bool(flagged_error or (hist_disc is not None and hist_disc >= cfg["anomaly"]["error_fare_discount"])
                 or disc >= sc["error_bench_disc"])
    bonus = 1.0 if error else 0.0
    parts = {"prix": round(prix, 1), "budget": round(budget, 1), "destination": round(dest, 1),
             "vol": round(vol, 1), "duree": round(duree, 1), "valeur": round(valeur, 1), "bonus": bonus}
    total_score = round(prix + budget + dest + vol + duree + valeur + bonus, 1)
    return Score(total=min(total_score, sc["max_score"]), parts=parts, discount=disc, error_fare=error)
