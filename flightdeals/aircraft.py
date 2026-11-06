"""Règle gros-porteur : au-delà de 5 h de vol, double couloir obligatoire.

Source : routes.dat d'OpenFlights (équipements par ligne). Ce fichier est ancien et
partiel : il sert à *éliminer* les lignes servies uniquement en monocouloir et à
*confirmer probablement* les autres. Pas de certitude sans le vol exact -> "unverified".
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

# Codes IATA d'équipement
WIDEBODY = {
    "330", "332", "333", "338", "339", "33X", "340", "342", "343", "345", "346",
    "350", "358", "359", "35K", "380", "388", "747", "744", "74H", "74E", "748",
    "767", "762", "763", "764", "76W", "777", "772", "773", "77L", "77W", "77X",
    "787", "788", "789", "78X", "781", "M11", "ILW", "IL9", "A3ST",
}
NARROWBODY = {
    "318", "319", "320", "321", "31", "32A", "32B", "32N", "32Q", "32S", "73G",
    "737", "73H", "73J", "73W", "73C", "733", "734", "735", "736", "738", "739",
    "7M8", "7M9", "752", "753", "757", "E90", "E75", "E70", "E95", "E190", "CR2",
    "CR7", "CR9", "CRJ", "AT7", "AT5", "DH4", "BEH", "SU9", "100", "146", "143",
}

TEXT_WIDE = ("a330", "a340", "a350", "a380", "787", "777", "747", "767", "dreamliner")
TEXT_NARROW = ("a320", "a321", "a319", "737", "757", "e190", "a220")


def classify_text(text: str):
    """True=gros-porteur, False=monocouloir, None=inconnu, d'après un texte libre."""
    t = text.lower()
    if any(k in t for k in TEXT_WIDE):
        return True
    if any(k in t for k in TEXT_NARROW):
        return False
    return None


@lru_cache(maxsize=1)
def _load_routes(path: str):
    routes: dict[tuple[str, str], set[str]] = {}
    p = Path(path)
    if not p.exists():
        return routes
    with p.open(newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 9:
                continue
            src, dst, equip = row[2], row[4], row[8]
            if not equip:
                continue
            routes.setdefault((src, dst), set()).update(equip.split())
    return routes


def check_route(origin, dest_airports: list[str], transfers: int, hours: float,
                long_haul_hours: float, routes_path: str):
    """-> (statut, note). Statut parmi not_required, widebody_probable, unverified, REJECT."""
    if hours <= long_haul_hours:
        return "not_required", f"vol de {hours:.1f} h, pas de contrainte d'avion"
    if transfers > 0:
        return "unverified", "escale(s) : type d'avion de chaque tronçon à vérifier avant d'acheter"
    routes = _load_routes(routes_path)
    equip: set[str] = set()
    for o in ([origin] if isinstance(origin, str) else origin):
        for d in dest_airports:
            equip |= routes.get((o, d), set())
            equip |= routes.get((d, o), set())
    if not equip:
        return "unverified", "ligne absente de la base d'équipements : vérifier le type d'avion"
    wide = equip & WIDEBODY
    if wide:
        return "widebody_probable", f"gros-porteur observé sur cette ligne ({', '.join(sorted(wide))}) ; vérifier le vol exact"
    if equip <= NARROWBODY:
        return "REJECT", f"ligne servie en monocouloir uniquement ({', '.join(sorted(equip))})"
    return "unverified", f"équipements inconnus ({', '.join(sorted(equip))})"
