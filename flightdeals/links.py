"""Liens pour VÉRIFIER le prix en direct et RÉSERVER chez la compagnie (jamais chez un intermédiaire)."""
from __future__ import annotations

from datetime import date
from typing import Optional
from urllib.parse import quote

from . import baggage


def google_flights(origin: str, dest_name: str, depart: Optional[date], ret: Optional[date]) -> str:
    """Recherche Google Flights déjà remplie (prix en direct, toutes compagnies, bagages affichés) pour les dates exactes."""
    q = f"Flights from {origin} to {dest_name}"
    if depart:
        q += f" on {depart.isoformat()}"
        if ret:
            q += f" through {ret.isoformat()}"
    return f"https://www.google.com/travel/flights?q={quote(q)}&curr=EUR&hl=fr"


def airline_site(code: str) -> str:
    return baggage.info(code).get("site", "")


def build(origin: str, dest_name: str, depart, ret, airline: str, source_link: str = "") -> dict:
    return {"google_flights": google_flights(origin, dest_name, depart, ret),
            "airline_site": airline_site(airline), "airline_name": baggage.info(airline).get("name", airline or ""),
            "source": source_link}
