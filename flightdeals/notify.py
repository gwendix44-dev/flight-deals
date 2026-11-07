"""Alertes : une Issue GitHub par affaire (GitHub envoie l'email + la notif mobile)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import webpush
from .core import Verdict

LABEL = {"error_fare": "🚨 ERREUR DE PRIX", "deal": "✈️ Très bonne affaire", "business_deal": "💺 Business pas cher", "stopover_deal": "🔀 Montage d'escales"}
AIRCRAFT = {
    "widebody_probable": "Gros-porteur probable sur la ligne (à vérifier sur le vol exact)",
    "unverified": "⚠️ Type d'avion NON vérifié : contrôler que c'est un double couloir avant d'acheter",
    "not_required": "Vol court (< 5 h) : pas de contrainte d'avion",
}


def title(v: Verdict) -> str:
    o = v.offer
    if v.kind == "business_deal":
        return f"{LABEL[v.kind]} {v.score}/11 · {o.origin}→{v.dest_city} · {o.price_eur:.0f} € A/R"
    return f"{LABEL[v.kind]} {v.score}/11 · {o.origin}→{v.dest_city} · séjour ~{v.trip_total} €"


def body(v: Verdict) -> str:
    o = v.offer
    dates = f"{o.depart} → {o.return_date}" if o.depart else "dates à voir sur le lien"
    lines = [
        title(v), *([f"NOTE : {v.score}/11  ({v.score_line})"] if v.score else []), "",
        f"Trajet : {o.origin} ⇄ {v.dest_city} ({v.country}) · {v.distance_km} km · ~{v.flight_hours} h · "
        f"{'direct' if o.transfers == 0 else str(o.transfers) + ' escale(s)'}",
        f"Cabine : {'Business' if o.cabin == 'business' else 'Économique'}   Dates : {dates}",
        (f"Prix du vol A/R AVEC sac à dos + bagage cabine : {v.flight_all_in:.0f} €"
         + (f"  (tarif affiché {o.price_eur:.0f} € + supplément bagages estimé {v.bag_supplement:.0f} €)" if v.bag_supplement else ""))
        if v.kind != "business_deal" else f"Prix du vol A/R en business : {o.price_eur:.0f} €",
        f"🎒 Bagages : {v.bag_note}" if v.bag_note else "",
        f"Séjour {v.stay_days} j en backpacker : ~{v.stay_cost} € sur place" + (" (indicatif, non pris en compte)" if v.kind == "business_deal" else ""),
        *[f"     · {lab} : {amt} €" for lab, amt in v.cost_lines],
        *([f"➜ Prix du vol : {o.price_eur:.0f} € A/R en business"] if v.kind == "business_deal" else
          [f"➜ COÛT TOTAL ESTIMÉ : ~{v.trip_total} € (vols + tout le séjour)"]),
        f"✔ {v.verification}" if v.verification else "",
        *(["", "Itinéraire (billets séparés) :", *[f"  {x}" for x in v.itinerary]] if v.itinerary else []),
        "", "Pourquoi :", *[f"  • {r}" for r in v.reasons],
        "", "👎 Pas pour toi ? Réponds en commentaire à cette Issue (ou bouton « Refuser » du dashboard) en expliquant "
            "pourquoi : trop cher, séjour trop court, trop d'escales, destination déjà vue… L'appli s'adapte aussitôt.",
        *(["⚠️ Billets séparés : aucune protection si un vol est en retard ; bagages à récupérer et ré-enregistrer à chaque escale ; vérifier les visas de transit."] if v.kind == "stopover_deal" else []),
        f"Avion : {AIRCRAFT.get(v.aircraft, v.aircraft)}" + (f" — {v.aircraft_note}" if v.aircraft in ('widebody_probable', 'unverified') else ""),
        f"Source du prix : {o.source}" + (f" — « {o.title} »" if o.title else "") + " (cache d'un moteur de recherche, pas un tarif garanti)",
        "", "AVANT D'ACHETER (2 minutes) :",
        f"  1. Vérifie le prix EN DIRECT (Google Flights, dates déjà remplies) : {v.links.get('google_flights', '')}"
        if v.links.get("google_flights") else "  1. Vérifie le prix en direct sur Google Flights pour ces dates exactes",
        *(["  1. Vérifie chaque billet en direct :", *[f"     - {u}" for u in v.links.get("google_flights_legs", [])]] if v.links.get("google_flights_legs") else []),
        f"  2. Achète sur le SITE OFFICIEL de la compagnie ({v.links.get('airline_name') or 'voir ci-dessus'}) : {v.links.get('airline_site')}"
        if v.links.get("airline_site") else "  2. Achète sur le site officiel de la compagnie, pas chez un intermédiaire",
        *(["  2. Sites officiels : " + " · ".join(v.links.get("airline_sites", []))] if v.links.get("airline_sites") else []),
        "  3. Contrôle à l'étape de réservation que le tarif choisi inclut bien un sac à dos + un bagage cabine.",
        f"  (lien du moteur de recherche d'origine : {o.link})" if o.link else "",
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
            resp = json.loads(urllib.request.urlopen(req, timeout=20).read())
            v.issue = resp.get("number")
            sent.append(v)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            print(f"[issues] échec HTTP {e.code} : {detail}")
            if e.code in (401, 403, 404, 410):   # accès/permission : inutile d'insister
                break
        except Exception as e:
            print(f"[issues] échec : {e}")
    return sent


def dashboard_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return ""
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/?fresh=1"      # ?fresh=1 : le dashboard lit les données sans attendre Pages


def _ntfy(payload: dict) -> bool:
    """Canal optionnel (ntfy.sh) : seulement si NTFY_TOPIC est défini. Non nécessaire : les notifications natives suffisent."""
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return False
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(dict(payload, topic=topic)).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "flight-deals"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
        return True
    except Exception as e:
        print(f"[ntfy] échec : {e}")
        return False


def _deliver(title_: str, message: str, priority: int, tags: list, link: str = "") -> bool:
    """Notification push : native (Web Push) en premier ; ntfy en option. True si au moins un canal a livré."""
    click = dashboard_url()
    native = webpush.send({"title": title_, "body": message, "url": click or "./?fresh=1", "tag": "fd-" + str(abs(hash(title_)) % 10**6)})
    nt = {"title": title_, "message": message, "priority": priority, "tags": tags}
    if click:
        nt["click"] = click
    if link.startswith("http"):
        nt["actions"] = [{"action": "view", "label": "Voir l'offre", "url": link}]
    other = _ntfy(nt)
    if not native and not other and not (webpush.configured() or os.environ.get("NTFY_TOPIC")):
        print("[push] aucune notification configurée (secrets VAPID_PRIVATE_KEY + PUSH_SUBSCRIPTION) : les Issues GitHub restent actives")
    return bool(native or other)


def send_push(vs: list[Verdict]) -> list[Verdict]:
    """Une notification par offre (10/10 immédiats). Retourne les offres réellement notifiées."""
    sent = []
    for v in vs:
        o = v.offer
        biz = v.kind == "business_deal"
        msg = (f"{o.price_eur:.0f} € A/R en business" if biz else f"Vol {v.flight_all_in:.0f} € bagages inclus · séjour complet ~{v.trip_total} €"
               ) + f" · {v.distance_km} km"
        if v.reasons:
            msg += "\n" + v.reasons[-1]
        if _deliver(title(v), msg, 5 if v.kind == "error_fare" else 4,
                    ["airplane", "rotating_light"] if v.kind == "error_fare" else ["airplane"], o.link):
            sent.append(v)
    return sent


def send_push_summary(vs: list[Verdict], label: str) -> list[Verdict]:
    """UNE notification pour tout un créneau (12h / 19h) : la liste des deals ; un tap ouvre le dashboard."""
    std = [v for v in vs if v.kind != "business_deal"]
    biz = [v for v in vs if v.kind == "business_deal"]
    lines = [f"• {v.score}/11 {v.offer.origin}→{v.dest_city} : vol {v.flight_all_in:.0f} € bagages inclus, séjour ~{v.trip_total} €" for v in std]
    lines += [f"• 💺 {v.offer.origin}→{v.dest_city} : {v.offer.price_eur:.0f} € A/R en business" for v in biz]
    parts = ([f"{len(std)} deal(s)"] if std else []) + ([f"{len(biz)} business"] if biz else [])
    ok = _deliver(f"✈️ {label} : " + " + ".join(parts), "\n".join(lines), 4, ["airplane"])
    return list(vs) if ok else []
