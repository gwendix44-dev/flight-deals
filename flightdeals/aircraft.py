"""Règle gros-porteur : au-delà de 5 h de vol, avion à double couloir obligatoire.

Source : routes.dat (OpenFlights), partiel et ancien. Il sert à confirmer « probable » ou à éliminer
les lignes servies seulement en monocouloir. Sans donnée : « unverified ».
"""
from __future__ import annotations

import csv
from functools import lru_cache

from .util import ROOT

WIDE = {"330", "332", "333", "338", "339", "33X", "340", "342", "343", "345", "346", "350", "358", "359", "35K",
        "380", "388", "747", "744", "74H", "74E", "748", "767", "762", "763", "764", "76W", "777", "772", "773",
        "77L", "77W", "77X", "787", "788", "789", "78X", "781", "M11", "ILW", "IL9"}
NARROW = {"318", "319", "320", "321", "32A", "32B", "32N", "32Q", "32S", "73G", "737", "73H", "73J", "73W", "73C",
          "733", "734", "735", "736", "738", "739", "7M8", "7M9", "752", "753", "757", "E90", "E75", "E70", "E95",
          "CR2", "CR7", "CR9", "AT7", "AT5", "DH4", "SU9"}


@lru_cache(maxsize=1)
def _routes() -> dict:
    out: dict = {}
    p = ROOT / "data" / "routes.dat"
    if not p.exists():
        return out
    with p.open(newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f):
            if len(row) >= 9 and row[8]:
                out.setdefault((row[2], row[4]), set()).update(row[8].split())
    return out


def flight_hours(km: float, cfg: dict, transfers: int = 0) -> float:
    return km / cfg["aircraft"]["cruise_kmh"] + 0.5 + 2.0 * transfers


def check(origin: str, dest_airports: list[str], km: float, transfers: int, cfg: dict) -> tuple[str, str]:
    """-> (statut, note) ; statut : not_required | widebody | unverified | reject."""
    if flight_hours(km, cfg) <= cfg["aircraft"]["long_haul_hours"]:
        return "not_required", "Vol court (moins de 5 h) : pas d'exigence d'avion."
    if transfers > 0:
        return "unverified", "Avec escale : type d'avion des tronçons à vérifier (gros-porteur obligatoire au-delà de 5 h)."
    eq: set[str] = set()
    for ap in dest_airports:
        eq |= _routes().get((origin, ap), set())
    if not eq:
        return "unverified", "Type d'avion non confirmé pour cette ligne."
    if eq & WIDE:
        return "widebody", "Gros-porteur probable (" + ", ".join(sorted(eq & WIDE)) + ")."
    if eq & NARROW:
        return "reject", "Ligne servie en monocouloir (" + ", ".join(sorted(eq & NARROW)) + ")."
    return "unverified", "Type d'avion inconnu."
