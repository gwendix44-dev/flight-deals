"""Alertes : une Issue GitHub par affaire (GitHub envoie l'email + la notif mobile)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .core import Verdict

LABEL = {"error_fare": "🚨 ERREUR DE PRIX", "deal": "✈️ Très bonne affaire", "business_deal": "💺 Business pas cher", "stopover_deal": "🔀 Montage d'escales"}
AIRCRAFT = {
    "widebody_probable": "Gros-porteur probable sur la ligne (à vérifier sur le vol exact)",
    "unverified": "⚠️ Type d'avion NON vérifié : contrôler que c'est un double couloir avant d'acheter",
    "not_required": "Vol court (< 5 h) : pas de contrainte d'avion",
}


def title(v: Verdict) -> str:
    o = v.offer
    return f"{LABEL[v.kind]} {o.origin}→{v.dest_city} {o.price_eur:.0f} €"


def body(v: Verdict) -> str:
    o = v.offer
    dates = f"{o.depart} → {o.return_date}" if o.depart else "dates à voir sur le lien"
    lines = [
        title(v), "",
        f"Trajet : {o.origin} ⇄ {v.dest_city} ({v.country}) · {v.distance_km} km · ~{v.flight_hours} h · "
        f"{'direct' if o.transfers == 0 else str(o.transfers) + ' escale(s)'}",
        f"Cabine : {'Business' if o.cabin == 'business' else 'Économique'}   Dates : {dates}",
        f"Prix du vol A/R : {o.price_eur:.0f} €",
        f"Séjour {v.stay_days} j en backpacker : ~{v.stay_cost} € ({v.daily_budget:.0f} €/j + marge + frais)",
        f"➜ COÛT TOTAL ESTIMÉ : ~{v.trip_total} €",
        *(["", "Itinéraire (billets séparés) :", *[f"  {x}" for x in v.itinerary]] if v.itinerary else []),
        "", "Pourquoi :", *[f"  • {r}" for r in v.reasons],
        *(["⚠️ Billets séparés : aucune protection si un vol est en retard ; bagages à récupérer et ré-enregistrer à chaque escale ; vérifier les visas de transit."] if v.kind == "stopover_deal" else []),
        f"Avion : {AIRCRAFT.get(v.aircraft, v.aircraft)}" + (f" — {v.aircraft_note}" if v.aircraft in ('widebody_probable', 'unverified') else ""),
        f"Source : {o.source}" + (f" — « {o.title} »" if o.title else ""),
        f"Réserver : {o.link or 'rechercher la route sur Google Flights / Skyscanner / Kiwi'}",
        "", "Les erreurs de prix durent parfois quelques heures et peuvent être annulées :",
        "ne réserve pas d'hébergement non remboursable avant confirmation du billet.",
    ]
    return "\n".join(lines)


LABELS = {"error_fare": "erreur-de-prix", "deal": "bonne-affaire", "business_deal": "business", "stopover_deal": "montage-escales"}


def create_issues(vs: list[Verdict]) -> list[Verdict]:
    """Crée une Issue par affaire. Retourne celles réellement créées."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        print("[issues] GITHUB_TOKEN / GITHUB_REPOSITORY absents : aucune Issue créée")
        return []
    sent = []
    for v in vs:
        data = json.dumps({"title": title(v), "body": body(v), "labels": [LABELS[v.kind]]}).encode()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues", data=data, method="POST",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json", "User-Agent": "flight-deals"})
        try:
            urllib.request.urlopen(req, timeout=20).read()
            sent.append(v)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            print(f"[issues] échec HTTP {e.code} : {detail}")
            if e.code in (401, 403, 404, 410):   # accès/permission : inutile d'insister
                break
        except Exception as e:
            print(f"[issues] échec : {e}")
    return sent
