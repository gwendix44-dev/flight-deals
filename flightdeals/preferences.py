"""Préférences apprises à partir de tes refus.

Quand tu refuses une offre en expliquant pourquoi (« trop cher », « séjour trop court »…), `learn()` transforme ta
phrase en réglages durables, stockés dans docs/preferences.json. `load_cfg()` les applique par-dessus config.json
à chaque scan. Les règles sont des mots-clés (gratuit, sans IA, prévisible) ; tout ce qui n'est pas compris est
signalé dans la réponse pour que tu puisses reformuler.
"""
from __future__ import annotations

import copy
import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

from . import scoring
from .airports import secrecy

ROOT = Path(__file__).resolve().parent.parent
PREFS_PATH = ROOT / "docs" / "preferences.json"

DEFAULT = {
    "total_cap_eur": None, "cap_by_tier": {}, "business_cap_eur": None, "min_stay_extra": 0, "max_stay_days": None,
    "max_distance_km": None, "min_distance_km": None, "max_flight_hours": None,
    "max_transfers": None, "strict_aircraft": False, "stopovers_disabled": False,
    "excluded_destinations": [], "excluded_countries": [], "excluded_months": [],
    "min_secrecy": None, "min_score_bonus": 0.0, "refused_issues": [], "refused_keys": [],
}


def load_prefs(path: Path | None = None) -> dict:
    path = path or PREFS_PATH                      # lu à l'appel (et non à la définition) : testable et redirigeable
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    return {**copy.deepcopy(DEFAULT), **data}


def apply_prefs(cfg: dict, p: dict) -> dict:
    """config.json + préférences -> configuration effective du scan."""
    c = copy.deepcopy(cfg)
    if p.get("business_cap_eur"):
        c["business"]["flight_cap_eur"] = min(c["business"]["flight_cap_eur"], p["business_cap_eur"])
    tiers = c["economy"]["total_trip_cap_eur"]
    for i, (upto, cap) in enumerate(tiers):
        cap = min(cap, p.get("total_cap_eur") or cap, (p.get("cap_by_tier") or {}).get(str(i), cap))
        tiers[i] = [upto, cap]
    c["stay_days"]["min_extra_days"] = p.get("min_stay_extra", 0)
    if p.get("max_stay_days"):
        c["stay_days"]["max"] = min(c["stay_days"]["max"], p["max_stay_days"])
    if p.get("max_transfers") is not None:
        c["max_transfers"] = min(c.get("max_transfers", 2), p["max_transfers"])
    if p.get("strict_aircraft"):
        c["aircraft"]["strict"] = True
    if p.get("stopovers_disabled"):
        c["stopovers"]["enabled"] = False
    c["excluded_countries"] = sorted(set(c.get("excluded_countries", [])) | set(p.get("excluded_countries", [])))
    c["scoring"]["min_score"] = round(min(c["scoring"]["min_score"] + p.get("min_score_bonus", 0), 10.8), 1)
    c["limits"] = {k: p.get(k) for k in ("max_distance_km", "min_distance_km", "max_flight_hours", "min_secrecy")}
    c["limits"]["excluded_destinations"] = p.get("excluded_destinations", [])
    c["limits"]["excluded_months"] = p.get("excluded_months", [])
    return c


def load_cfg() -> dict:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    return apply_prefs(cfg, load_prefs())


def violates(cfg: dict, *, dest: str, km: float, hours: float, depart, stay: int) -> bool:
    """True si l'offre contredit une de tes préférences apprises."""
    lim = cfg.get("limits") or {}
    if dest in lim.get("excluded_destinations", []):
        return True
    if lim.get("max_distance_km") and km > lim["max_distance_km"]:
        return True
    if lim.get("min_distance_km") and km < lim["min_distance_km"]:
        return True
    if lim.get("max_flight_hours") and hours > lim["max_flight_hours"]:
        return True
    if depart and depart.month in lim.get("excluded_months", []):
        return True
    if lim.get("min_secrecy") is not None and secrecy(dest) < lim["min_secrecy"]:
        return True
    return False


# ------------------------------------------------------------------ apprentissage
def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def _num(text: str, unit: str) -> Optional[int]:
    m = re.search(r"(\d{1,4})\s*" + unit, text)
    return int(m.group(1)) if m else None


def learn(prefs: dict, text: str, deal: Optional[dict], cfg: dict) -> tuple:
    """Retourne (prefs mises à jour, messages lisibles). `deal` = l'offre refusée (dict de docs/deals.json)."""
    p = copy.deepcopy(prefs)
    t = _norm(text)
    msgs: list[str] = []
    d = deal or {}
    km = d.get("distance_km")
    tier = next((i for i, (u, _) in enumerate(cfg["economy"]["total_trip_cap_eur"]) if (km or 8000) <= u), 0)
    cap_now = cfg["economy"]["total_trip_cap_eur"][tier][1]      # déjà intégré aux préférences existantes

    def has(*words):
        return any(re.search(w, t) for w in words)

    # --- prix / budget
    if has(r"trop cher", r"\bcher\b", r"budget", r"depasse", r"prix (trop )?(eleve|haut)"):
        n = _num(t, r"(?:€|euros?\b|eur\b)")
        if d.get("kind") == "business_deal":
            n = n or max(400, int(d["offer"]["price_eur"] * 0.9 // 50 * 50))
            p["business_cap_eur"] = min(p["business_cap_eur"] or 10**6, n)
            msgs.append(f"Plafond business abaissé à {p['business_cap_eur']} € A/R.")
        elif n and 300 <= n <= 5000:
            p["total_cap_eur"] = n
            msgs.append(f"Budget total maximum fixé à {n} €.")
        else:
            base = d["trip_total"] if d.get("trip_total") else cap_now
            n = max(600, int(base * 0.9 // 50 * 50))
            if n < cap_now:
                p["cap_by_tier"][str(tier)] = n
                msgs.append(f"Budget total maximum abaissé à {n} € pour les destinations à cette distance"
                            + (f" (l'offre refusée coûtait ~{d['trip_total']} €)." if d.get("trip_total") else "."))

    # --- durée du séjour / durée du vol
    flight_len = has(r"\bvol\b.*\blong", r"\blong\b.*\bvol\b", r"duree du vol", r"trop (d'heures|de temps) (de vol|dans l'avion)", r"trajet (trop )?long")
    if has(r"trop court", r"sejour (trop )?court", r"pas assez (longtemps|de jours)", r"plus de jours", r"plus longtemps"):
        n = _num(t, r"jours?")
        base = scoring.min_stay_for(km, cfg) - cfg["stay_days"].get("min_extra_days", 0) if km else None
        extra = max(0, n - base) if (n and base) else p["min_stay_extra"] + 2
        p["min_stay_extra"] = min(7, max(p["min_stay_extra"], extra))
        msgs.append(f"Séjours plus longs exigés : +{p['min_stay_extra']} jour(s) par rapport au minimum selon la distance.")
    if flight_len:
        h = max(5.0, round((d.get("flight_hours") or 14) - 1.5, 1))
        p["max_flight_hours"] = min(p["max_flight_hours"] or 99, h)
        msgs.append(f"Durée de vol limitée à {p['max_flight_hours']} h.")
    elif has(r"trop long", r"sejour (trop )?long"):
        n = _num(t, r"jours?")
        v = n or max(7, (d.get("stay_days") or 14) - 2)
        p["max_stay_days"] = min(p["max_stay_days"] or 99, v)
        msgs.append(f"Séjour limité à {p['max_stay_days']} jours.")

    # --- distance
    if has(r"trop loin", r"distance"):
        v = max(2500, int((km or 8000) - 800))
        p["max_distance_km"] = min(p["max_distance_km"] or 10**6, v)
        msgs.append(f"Distance maximale : {p['max_distance_km']} km.")
    if has(r"trop pres", r"trop proche"):
        v = int((km or 4000) + 500)
        p["min_distance_km"] = max(p["min_distance_km"] or 0, v)
        msgs.append(f"Distance minimale : {p['min_distance_km']} km.")

    # --- escales / billets séparés / avion
    separate = has(r"montage", r"billets? separes?", r"risque", r"correspondance (ratee|manquee)")
    if separate:
        p["stopovers_disabled"] = True
        msgs.append("Montages à billets séparés désactivés.")
    if has(r"escale") and not separate:
        mx = 0 if has(r"direct") else max(0, int(d.get("offer", {}).get("transfers", 1)) - 1)
        p["max_transfers"] = min(p["max_transfers"] if p["max_transfers"] is not None else 2, mx)
        msgs.append(f"Escales maximum : {p['max_transfers']}.")
    if has(r"avion", r"couloir", r"a320", r"737", r"monocouloir"):
        p["strict_aircraft"] = True
        msgs.append("Mode strict avion : seuls les vols dont le gros-porteur est confirmé seront proposés.")

    # --- destination / période / rareté / niveau d'exigence
    if has(r"destination", r"deja (vu|fait|visite)", r"connais", r"pas envie", r"pas interess", r"ville", r"pays"):
        if d.get("offer", {}).get("dest") and not has(r"pays"):
            dest = d["offer"]["dest"]
            if dest not in p["excluded_destinations"]:
                p["excluded_destinations"].append(dest)
            msgs.append(f"Destination exclue : {d.get('dest_city', dest)}.")
        elif d.get("country"):
            if d["country"] not in p["excluded_countries"]:
                p["excluded_countries"].append(d["country"])
            msgs.append(f"Pays exclu : {d['country']}.")
    if has(r"periode", r"\bdates?\b", r"\bmois\b", r"vacances", r"travail", r"indisponible"):
        dep = d.get("offer", {}).get("depart")
        if dep and len(dep) >= 7:
            m = int(dep[5:7])
            if m not in p["excluded_months"]:
                p["excluded_months"].append(m)
            msgs.append(f"Départs exclus pour le mois {m:02d}.")
    if has(r"touristique", r"trop connu", r"banal", r"mainstream", r"pas assez secret", r"commun"):
        base = secrecy(d["offer"]["dest"]) if d.get("offer", {}).get("dest") else 0.5
        p["min_secrecy"] = min(1.5, max(p["min_secrecy"] or 0, base + 0.5))
        msgs.append("Destinations plus confidentielles exigées.")
    if has(r"pas assez exceptionnel", r"\bmoyen\b", r"mediocre", r"\bbof\b", r"pas assez bien"):
        p["min_score_bonus"] = round(min(1.0, p["min_score_bonus"] + 0.3), 1)
        msgs.append(f"Exigence relevée : seuil de note +{p['min_score_bonus']}.")

    return p, msgs
