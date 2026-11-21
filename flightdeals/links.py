"""Liens de vérification : Google Flights (dates préremplies) et site officiel."""
from __future__ import annotations

import urllib.parse


def google_flights_url(o, airports) -> str:
    dest = (airports or [o.dest])[0]
    cabin = "business class" if o.cabin == "business" else ""
    if o.depart and o.return_date:
        q = f"Flights from {o.origin} to {dest} on {o.depart.isoformat()} through {o.return_date.isoformat()} {cabin}".strip()
    else:
        q = f"Flights from {o.origin} to {dest} {cabin}".strip()
    return "https://www.google.com/travel/flights?hl=fr&curr=EUR&q=" + urllib.parse.quote(q)
