"""Vérification EN DIRECT d'un prix (Google Flights via l'API SerpApi) : une source indépendante du cache de l'agrégateur.

Optionnelle : active seulement si le secret SERPAPI_KEY existe. Le plan gratuit de SerpApi est limité (de l'ordre de 100
recherches par mois : voir leur page tarifs) ; on ne vérifie donc que les FINALISTES d'une publication, avec un budget mensuel
(`live.monthly_budget`) suivi dans data/live_usage.json. Sans clé ou sans quota, l'offre reste publiée mais marquée « prix
non confirmé en direct ».

Ce que la vérification apporte : le prix réel du moment pour les dates exactes, la compagnie, le TYPE D'AVION de chaque
tronçon (donc la règle gros-porteur au-delà de 5 h devient vérifiée, plus seulement probable), et le niveau de prix de Google
(bas / habituel / élevé). Les champs lus sont ceux documentés par SerpApi ; tout changement de format est consigné dans le
journal, jamais interprété au hasard.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import aircraft
from .airports import DESTINATIONS
from .common import ROOT, _load, _save

USAGE = ROOT / "data" / "live_usage.json"
ENDPOINT = "https://serpapi.com/search.json"


@dataclass
class Live:
    status: str                       # confirmed | higher | gone | unavailable
    price: Optional[float] = None
    airlines: list = field(default_factory=list)
    aircraft: list = field(default_factory=list)       # types d'avion annoncés, un par tronçon
    level: str = ""                                    # low | typical | high (Google)
    typical: list = field(default_factory=list)        # [bas, haut] de la fourchette habituelle
    detail: str = ""


def key() -> str:
    return os.environ.get("SERPAPI_KEY", "").strip()


def month_id(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def used(now: Optional[datetime] = None) -> int:
    u = _load(USAGE, {})
    return u.get("used", 0) if u.get("month") == month_id(now) else 0


def can_spend(cfg: dict, now: Optional[datetime] = None) -> bool:
    return bool(key()) and cfg.get("live", {}).get("enabled", False) and used(now) < cfg["live"]["monthly_budget"]


def _spend(now: Optional[datetime] = None) -> None:
    _save(USAGE, {"month": month_id(now), "used": used(now) + 1})


def _get(params: dict) -> dict:
    url = ENDPOINT + "?" + urllib.parse.urlencode({**params, "api_key": key()})
    req = urllib.request.Request(url, headers={"User-Agent": "flight-deals"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


def _code(flight_number: str) -> str:
    """'AF 123' -> 'AF'."""
    return (flight_number or "").split(" ")[0].upper()


def parse(data: dict, airline: str, claimed: float, tolerance: float) -> Live:
    """Lit une réponse SerpApi Google Flights et la compare au prix annoncé. Fonction pure (testée sans réseau)."""
    if data.get("error"):
        return Live("unavailable", detail=f"SerpApi : {str(data['error'])[:120]}")
    options = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    options = [o for o in options if isinstance(o, dict) and isinstance(o.get("price"), (int, float)) and o.get("flights")]
    if not options:
        keys = ", ".join(sorted(data.keys()))[:160]
        return Live("gone", detail=f"aucun vol trouvé par Google Flights pour ces dates (champs reçus : {keys})")
    mine = [o for o in options if any(_code(f.get("flight_number", "")) == (airline or "").upper() for f in o["flights"])] if airline else []
    pick = min(mine or options, key=lambda o: o["price"])
    segs = pick["flights"]
    ins = data.get("price_insights") or {}
    live = Live("confirmed", price=float(pick["price"]),
                airlines=sorted({f.get("airline", "") for f in segs} - {""}),
                aircraft=[f.get("airplane", "") for f in segs],
                level=ins.get("price_level", ""), typical=list(ins.get("typical_price_range") or []))
    if airline and not mine:
        live.detail = f"la compagnie annoncée ({airline}) n'apparaît pas chez Google Flights : prix le plus bas trouvé, toutes compagnies"
    if live.price > claimed * (1 + tolerance):
        live.status = "higher"
        live.detail = f"prix en direct {live.price:.0f} € > prix annoncé {claimed:.0f} €"
    return live


def check(origin: str, dest: str, depart, ret, airline: str, claimed: float, cfg: dict) -> Live:
    """Une recherche Google Flights pour les dates exactes. Dépense 1 unité du budget mensuel."""
    airports = DESTINATIONS.get(dest, ("", "", 0, 0, []))[4] or [dest]
    params = {"engine": "google_flights", "departure_id": origin, "arrival_id": ",".join(airports),
              "outbound_date": depart.isoformat(), "return_date": ret.isoformat(), "type": "1", "currency": "EUR",
              "hl": "fr", "adults": "1", "travel_class": "1"}
    try:
        _spend()
        return parse(_get(params), airline, claimed, cfg["live"]["price_tolerance"])
    except Exception as e:
        return Live("unavailable", detail=f"vérification en direct impossible ({e})")


def aircraft_verdict(types: list, hours_per_leg: Optional[float] = None) -> str:
    """widebody | narrowbody | unknown d'après les types d'avion annoncés (un par tronçon)."""
    kinds = [aircraft.classify_text(t) for t in types if t]
    if not kinds or any(k is None for k in kinds):
        return "unknown"
    return "widebody" if all(kinds) else "narrowbody"
