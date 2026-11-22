"""Structures de données."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date


@dataclass
class Offer:
    origin: str
    dest: str                      # code de destination connue (ville)
    price: float
    depart: date | None = None
    return_date: date | None = None
    transfers: int = 0
    airline: str = ""
    cabin: str = "economy"        # economy | business
    source: str = "travelpayouts"
    link: str = ""
    title: str = ""
    flagged_error: bool = False
    dest_airport: str = ""
    flight_number: str = ""
    stopover: dict | None = None  # montage à billets séparés

    @property
    def key(self) -> str:
        """Clé STABLE (sans le prix) : un refus reste valable si le prix bouge."""
        raw = "|".join([self.origin, self.dest, self.cabin, str(self.depart or ""), str(self.return_date or ""),
                        "combo" if self.stopover else ""])
        return hashlib.sha1(raw.encode()).hexdigest()[:16]
