"""Bagages : sac à dos + bagage cabine DOIVENT être inclus dans le prix affiché."""
from __future__ import annotations

from .util import ROOT, read_json


def airlines() -> dict:
    return read_json(ROOT / "data" / "airlines.json", {})


def baggage_for(code: str, cfg: dict, cabin: str = "economy", round_trip: bool = True) -> dict:
    """-> {status, surcharge, airline, site, warning}. surcharge = supplément A/R à AJOUTER au prix du vol."""
    a = airlines().get(code)
    mult = 2 if round_trip else 1
    if cabin == "business":
        return {"status": "included", "surcharge": 0.0, "airline": (a or {}).get("name", code), "site": (a or {}).get("site", ""), "warning": ""}
    if not a or code.startswith("_"):
        return {"status": "unknown", "surcharge": float(cfg["baggage"]["unknown_airline_eur"]), "airline": code or "?",
                "site": "", "warning": "Compagnie inconnue : +60 € de bagages comptés par prudence."}
    bag = a.get("bag", "included")
    if bag == "fee":
        sur = float(a.get("fee", airlines().get("_default_fee_eur", 30))) * mult
        return {"status": "fee", "surcharge": sur, "airline": a["name"], "site": a.get("site", ""),
                "warning": f"Bagage cabine payant chez {a['name']} : +{sur:.0f} € ajoutés au prix."}
    warn = f"Confirme que le bagage cabine est inclus dans le tarif {a['name']} avant de payer." if bag == "likely" else ""
    return {"status": bag, "surcharge": 0.0, "airline": a["name"], "site": a.get("site", ""), "warning": warn}
