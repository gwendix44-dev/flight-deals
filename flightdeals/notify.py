"""Alertes : email (Gmail SMTP) + push ntfy.sh (notification dans l'appli/téléphone)."""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage

from .core import Verdict

LABEL = {"error_fare": "🚨 ERREUR DE PRIX", "deal": "✈️ Très bonne affaire", "business_deal": "💺 Business pas cher"}
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
        "", "Pourquoi :", *[f"  • {r}" for r in v.reasons],
        f"Avion : {AIRCRAFT.get(v.aircraft, v.aircraft)}" + (f" — {v.aircraft_note}" if v.aircraft in ('widebody_probable', 'unverified') else ""),
        f"Source : {o.source}" + (f" — « {o.title} »" if o.title else ""),
        f"Réserver : {o.link or 'rechercher la route sur Google Flights / Skyscanner / Kiwi'}",
        "", "Les erreurs de prix durent parfois quelques heures et peuvent être annulées :",
        "ne réserve pas d'hébergement non remboursable avant confirmation du billet.",
    ]
    return "\n".join(lines)


def send_email(vs: list[Verdict], to: str) -> bool:
    user, pwd = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and pwd):
        print("[email] GMAIL_USER / GMAIL_APP_PASSWORD absents : email non envoyé")
        return False
    msg = EmailMessage()
    msg["From"], msg["To"] = user, to
    msg["Subject"] = title(vs[0]) + (f" (+{len(vs) - 1} autres)" if len(vs) > 1 else "")
    msg.set_content("\n\n" + ("\n" + "─" * 40 + "\n\n").join(body(v) for v in vs))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(user, pwd)
        s.send_message(msg)
    return True


def send_push(vs: list[Verdict], click_url: str = "") -> bool:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("[ntfy] NTFY_TOPIC absent : push non envoyé")
        return False
    for v in vs:
        payload = {
            "topic": topic, "title": title(v), "message": f"Total séjour ~{v.trip_total} € · {v.offer.depart or ''}",
            "priority": 5 if v.kind == "error_fare" else 4, "tags": ["airplane"],
        }
        click = v.offer.link or click_url
        if click:
            payload["click"] = click
        req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
    return True
