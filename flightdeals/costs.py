"""Coût réaliste d'un séjour backpacker, poste par poste (data/costs.json, modifiable)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent


def load_costs() -> dict:
    return json.loads((ROOT / "data" / "costs.json").read_text(encoding="utf-8"))


def daily(costs: dict, cc: str) -> Optional[float]:
    c = costs.get(cc)
    return None if not c else c["lodging"] + c["food"] + c["transport"] + c["activities"]


def _is_peak(depart: Optional[date], days: int, cfg: dict) -> bool:
    """Le séjour chevauche-t-il la haute saison des fêtes (hébergement plus cher) ?"""
    pk = cfg["economy"].get("peak_season")
    if not (depart and pk):
        return False
    sm, sd = map(int, pk["start"].split("-"))
    em, ed = map(int, pk["end"].split("-"))
    d = depart
    for _ in range(days + 1):
        md = (d.month, d.day)
        if (sm, sd) <= md or md <= (em, ed):
            return True
        d += timedelta(days=1)
    return False


def positioning(origin: Optional[str], cfg: dict):
    """Trajet A/R depuis chez toi (Paris / Nantes) jusqu'à un aéroport de départ éloigné. -> (montant, libellé) ou None."""
    home = cfg.get("home")
    if not (home and origin) or origin in home["airports"]:
        return None
    table = home["positioning_eur"].get(origin)
    if not table:
        return home["default_positioning_eur"], f"Trajet A/R jusqu'à l'aéroport de départ ({origin}), estimation"
    frm = min(table, key=table.get)
    return table[frm], f"Trajet A/R {frm} → {origin} pour rejoindre l'aéroport de départ"


def stay_breakdown(costs: dict, cc: str, days: int, depart: Optional[date], cfg: dict, origin: Optional[str] = None):
    """-> (total_eur, lignes [(libellé, montant)]). None si le pays n'est pas dans la base.

    Si le vol part d'un autre aéroport que chez toi (Paris, Nantes), le trajet pour le rejoindre est ajouté ICI,
    dans le coût du séjour, et non dans le prix du vol (qui reste comparé au vrai tarif du vol)."""
    c = costs.get(cc)
    if not c:
        return None
    eco = cfg["economy"]
    peak = _is_peak(depart, days, cfg)
    lodging = c["lodging"] * days * (eco["peak_season"]["lodging_multiplier"] if peak else 1.0)
    inter = c["intercity"] * min(1.3, days / 14)
    visa_label = "Visa / autorisation d'entrée" + (f" ({c['visa_note']}, à revérifier)" if c.get("visa_note") else "")
    lines = [
        ("Hébergement (dortoir / chambre simple)" + (" — haute saison des fêtes" if peak else ""), lodging),
        ("Nourriture (cuisine locale)", c["food"] * days),
        ("Transports locaux", c["transport"] * days),
        ("Activités et visites", c["activities"] * days),
        ("Déplacements entre villes", inter),
        (visa_label, c["visa"]),
        ("Assurance voyage", eco["insurance_per_day"] * days),
        ("Transferts aéroport + SIM locale", eco["arrival_flat_eur"]),
    ]
    sub = sum(v for _, v in lines)
    buf = sub * eco["buffer_pct"] / 100
    lines.append((f"Marge imprévus ({eco['buffer_pct']} %)", buf))
    pos = positioning(origin, cfg)
    extra = 0.0
    if pos:
        extra = pos[0]
        lines.append(pos[::-1])
    return sub + buf + extra, [(k, round(v)) for k, v in lines if round(v) > 0]
