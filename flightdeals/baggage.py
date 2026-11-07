"""Sac à dos + bagage cabine : le tarif affiché doit les INCLURE.

Les sources de prix (agrégateurs) affichent le tarif nu. Sur un long voyage, un sac à dos (article personnel) ET un bagage
cabine sont indispensables : si la compagnie les facture en plus, on ajoute le supplément estimé AU PRIX DU VOL, avant de
noter l'offre et de calculer le budget. Barème : data/airlines.json (mes connaissances, à vérifier au moment de réserver).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from .common import ROOT


@lru_cache(maxsize=1)
def _table() -> dict:
    return json.loads((ROOT / "data" / "airlines.json").read_text(encoding="utf-8"))


@dataclass
class Bag:
    supplement: float          # EUR à ajouter au tarif affiché (aller-retour)
    status: str                # inclus | probable | supplement | inconnu
    note: str
    airline_name: str = ""
    site: str = ""


def info(code: str) -> dict:
    return _table().get((code or "").upper().strip(), {})


def one_way(code: str):
    """(supplément par sens, statut, nom de la compagnie)."""
    t = _table()
    c = info(code)
    if not c:
        return t["_default_fee_eur"], "inconnu", ""
    if c["bag"] == "fee":
        return c["fee"], "supplement", c["name"]
    return 0, ("inclus" if c["bag"] == "included" else "probable"), c["name"]


def assess(code: str, transfers: int = 0, directions: int = 2) -> Bag:
    """Supplément bagages d'un billet (aller-retour par défaut) selon la compagnie."""
    per_way, status, name = one_way(code)
    c = info(code)
    supp = per_way * directions
    label = name or (code or "compagnie inconnue")
    if status == "inclus":
        note = f"{label} : sac à dos + bagage cabine inclus dans le tarif économique standard (à confirmer au moment de réserver)"
    elif status == "probable":
        note = f"{label} : sac à dos + bagage cabine en général inclus, mais pas sur tous les tarifs (Basic/Light) : confirme avant de payer"
    elif status == "supplement":
        note = f"{label} : bagage cabine PAYANT en plus du sac à dos, supplément estimé {supp:.0f} € A/R ajouté au tarif"
    else:
        note = f"Compagnie « {code or '?'} » inconnue : supplément bagages de {supp:.0f} € A/R ajouté par prudence, à vérifier"
    if transfers > 0:
        note += " ; autres compagnies du trajet (escales) : politique bagages à vérifier"
    return Bag(supplement=float(supp), status=status, note=note, airline_name=name, site=c.get("site", ""))


def worst(statuses: list) -> str:
    order = ["inclus", "probable", "inconnu", "supplement"]
    return max(statuses, key=lambda s: order.index(s)) if statuses else "inconnu"
