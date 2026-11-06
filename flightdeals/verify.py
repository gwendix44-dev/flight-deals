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

from . import providers


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
    print(f"[verify] {len(kept)} offre(s) confirmée(s), {len(dropped)} écartée(s)")
    for d in dropped[:8]:
        print("   ✗", d)
    return kept
