"""Revérification d'une offre AVANT de l'afficher ou de t'alerter.

Contrôles :
  1. le prix existe toujours pour les dates exactes (sinon : écartée) ;
  2. il n'a pas augmenté de plus de `price_tolerance` (10 %) depuis la détection ;
  3. montages d'escales : CHAQUE billet (aller, correspondances, retour) est revérifié séparément ;
  4. impossible de joindre l'API : écartée (jamais affichée sans contrôle) ;
  5. offres des flux de bons plans (humains) : pas de dates exactes, donc marquées « à confirmer sur le lien ».
Les prix viennent toujours du cache Travelpayouts (quelques heures de retard possible) : la mention le rappelle.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Optional

from . import live as livemod, providers


DROPPED: list = []          # raisons des offres écartées par la revérification (reprises dans docs/status.json)


def verify_one(v, cfg: dict, token: str, today: date, price_fn: Optional[Callable] = None):
    """-> (ok, message). Ne modifie pas le prix détecté, ajoute la mention de vérification."""
    price_fn = price_fn or providers.exact_price
    tol = 1 + cfg["verification"]["price_tolerance"]
    o = v.offer
    stamp = today.strftime("%d/%m/%Y")
    try:
        if o.source.startswith("rss"):
            return True, ("Source : flux de bons plans (signalement humain). Dates et prix NON revérifiables automatiquement : "
                          "confirme-les sur le lien avant d'acheter.")
        if o.source == "combo-escales":
            checks = []
            for leg in v.legs:
                direct = None if leg is v.legs[-1] else True
                p = price_fn(leg.orig, leg.dest, leg.dep.date(), None, token, direct)
                if p is None:
                    return False, f"billet {leg.orig}→{leg.dest} du {leg.dep:%d/%m} introuvable à la revérification"
                if p > leg.price * tol:
                    return False, f"billet {leg.orig}→{leg.dest} remonté de {leg.price:.0f} à {p:.0f} €"
                checks.append(f"{leg.orig}→{leg.dest} {p:.0f} €")
            return True, f"Revérifié le {stamp} billet par billet : " + " · ".join(checks)
        if o.depart and o.return_date:
            p = price_fn(o.origin, o.dest, o.depart, o.return_date, token)
            if p is None:
                return False, "plus aucun billet à ces dates exactes"
            if p > o.price_eur * tol:
                return False, f"prix remonté de {o.price_eur:.0f} à {p:.0f} €"
            return True, (f"Revérifié le {stamp} pour les dates exactes ({o.depart:%d/%m} → {o.return_date:%d/%m}) : {p:.0f} €. "
                          "Prix issu du cache des moteurs de recherche : confirme sur le lien avant d'acheter.")
        return False, "dates incomplètes, impossible à vérifier"
    except Exception as e:                      # réseau, quota : on préfère écarter qu'afficher sans contrôle
        return False, f"vérification impossible ({e})"


def verify_all(verdicts: list, cfg: dict, token: Optional[str], today: date, price_fn: Optional[Callable] = None) -> list:
    """Vérifie les meilleures offres (déjà triées) et ne garde que celles qui passent."""
    if not token and price_fn is None:
        print("[verify] TRAVELPAYOUTS_TOKEN absent : aucune offre revérifiable, aucune affichée")
        kept = [v for v in verdicts if v.offer.source.startswith("rss")]
        for v in kept:
            v.verification = "Flux de bons plans : à confirmer sur le lien avant d'acheter."
        return kept
    kept, dropped = [], []
    for v in verdicts[: cfg["verification"]["max_checks"]]:
        ok, msg = verify_one(v, cfg, token, today, price_fn)
        if ok:
            v.verification = msg
            kept.append(v)
        else:
            dropped.append(f"{v.offer.origin}→{v.dest_city} {v.offer.price_eur:.0f}€ : {msg}")
            DROPPED.append(dropped[-1])
    print(f"[verify] {len(kept)} offre(s) confirmée(s), {len(dropped)} écartée(s)")
    for d in dropped[:8]:
        print("   ✗", d)
    return kept


def live_confirm(verdicts: list, cfg: dict, today: date, limit: int, check_fn: Optional[Callable] = None) -> tuple:
    """Confirme EN DIRECT (Google Flights) les finalistes, dans l'ordre, jusqu'à `limit` offres retenues.

    -> (retenues, écartées). Écartée = prix monté / vol introuvable / monocouloir sur un long vol. Si la vérification en direct
    n'est pas disponible (pas de clé, quota épuisé, panne) l'offre reste, avec un avertissement bien visible."""
    kept, dropped = [], []
    stamp = today.strftime("%d/%m/%Y")
    for v in verdicts:
        if len(kept) >= limit:
            break
        o = v.offer
        if o.source.startswith("rss") or o.source == "combo-escales" or not (o.depart and o.return_date):
            v.verification = (v.verification + " | " if v.verification else "") + \
                "⚠ Prix non confirmable en direct automatiquement (offre sans dates exactes ou montage) : vérifie sur les liens ci-dessous"
            kept.append(v)
            continue
        if check_fn is None and not livemod.can_spend(cfg):
            manual = ("Prix du cache d'un moteur de recherche, revérifié pour ces dates exactes : "
                      "confirme-le avec le bouton « 1 · Vérifier en direct » avant d'acheter")
            v.verification = (v.verification + " | " if v.verification else "") + (
                manual if not cfg.get("live", {}).get("enabled") else
                "⚠ Prix NON confirmé en direct (clé absente ou quota du mois épuisé) : vérifie sur Google Flights avant d'acheter")
            kept.append(v)
            continue
        res = (check_fn or livemod.check)(o.origin, o.dest, o.depart, o.return_date, o.airline, o.price_eur, cfg)
        if res.status in ("higher", "gone"):
            dropped.append(v)
            print(f"[live] ✗ {o.origin}→{v.dest_city} {o.price_eur:.0f}€ : {res.detail}")
            continue
        if res.status == "unavailable":
            print(f"[live] ? {o.origin}→{v.dest_city} : {res.detail}")
            v.verification = (v.verification + " | " if v.verification else "") + \
                "⚠ Confirmation en direct indisponible (" + res.detail[:80] + ") : vérifie sur Google Flights avant d'acheter"
            kept.append(v)
            continue
        kind = livemod.aircraft_verdict(res.aircraft)
        if kind == "narrowbody" and v.flight_hours > cfg["aircraft"]["long_haul_hours"]:
            dropped.append(v)
            print(f"[live] ✗ {o.origin}→{v.dest_city} : avion monocouloir annoncé sur un vol de {v.flight_hours} h ({', '.join(res.aircraft)})")
            continue
        if kind == "widebody":
            v.aircraft, v.aircraft_note = "widebody_confirmed", "Avions annoncés par Google Flights : " + ", ".join(res.aircraft)
        niv = {"low": "bas", "typical": "habituel", "high": "élevé"}.get(res.level, "")
        v.verification = (f"✔ Confirmé EN DIRECT sur Google Flights le {stamp} : {res.price:.0f} € pour ces dates exactes"
                          + (f" ({', '.join(res.airlines)})" if res.airlines else "")
                          + (f" · niveau de prix {niv}" if niv else "")
                          + (f" · fourchette habituelle {res.typical[0]}–{res.typical[1]} €" if len(res.typical) == 2 else "")
                          + (f" · {res.detail}" if res.detail else ""))
        kept.append(v)
    return kept, dropped
