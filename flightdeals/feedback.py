"""Traite un commentaire de refus : python -m flightdeals.feedback

Lancé par .github/workflows/feedback.yml à chaque commentaire sur une Issue. Variables d'environnement :
COMMENT_BODY, COMMENT_USER, ISSUE_NUMBER, GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_REPOSITORY_OWNER.
Sécurité : seul le propriétaire du dépôt peut modifier les préférences (le dépôt est public).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

from . import preferences
from .main import DEALS, ROOT, _load, _save

LOG = ROOT / "data" / "feedback.json"


def _api(method: str, path: str, payload: dict | None = None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{path}",
        data=json.dumps(payload).encode() if payload is not None else None, method=method,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "flight-deals"})
    return urllib.request.urlopen(req, timeout=20).read()


def describe(p: dict) -> str:
    rows = []
    if p["total_cap_eur"]: rows.append(f"budget total max {p['total_cap_eur']} €")
    if p.get("business_cap_eur"): rows.append(f"plafond business {p['business_cap_eur']} € A/R")
    for i, cap in sorted(p["cap_by_tier"].items()): rows.append(f"budget total max {cap} € (palier de distance n°{int(i) + 1})")
    if p["min_stay_extra"]: rows.append(f"séjour minimum +{p['min_stay_extra']} j")
    if p["max_stay_days"]: rows.append(f"séjour max {p['max_stay_days']} j")
    if p["max_distance_km"]: rows.append(f"distance max {p['max_distance_km']} km")
    if p["min_distance_km"]: rows.append(f"distance min {p['min_distance_km']} km")
    if p["max_flight_hours"]: rows.append(f"vol max {p['max_flight_hours']} h")
    if p["max_transfers"] is not None: rows.append(f"escales max {p['max_transfers']}")
    if p["strict_aircraft"]: rows.append("gros-porteur confirmé exigé")
    if p["stopovers_disabled"]: rows.append("montages à billets séparés désactivés")
    if p["excluded_destinations"]: rows.append("destinations exclues : " + ", ".join(p["excluded_destinations"]))
    if p["excluded_countries"]: rows.append("pays exclus : " + ", ".join(p["excluded_countries"]))
    if p["excluded_months"]: rows.append("mois exclus : " + ", ".join(f"{m:02d}" for m in p["excluded_months"]))
    if p["min_secrecy"] is not None: rows.append(f"rareté minimale {p['min_secrecy']}")
    if p["min_score_bonus"]: rows.append(f"seuil de note +{p['min_score_bonus']}")
    return "\n".join(f"- {r}" for r in rows) or "- aucune préférence apprise pour l'instant"


def main() -> int:
    body = (os.environ.get("COMMENT_BODY") or "").strip()
    user, owner = os.environ.get("COMMENT_USER", ""), os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    number = int(os.environ.get("ISSUE_NUMBER", "0"))
    if not body or user.lower() != owner.lower() or user.endswith("[bot]"):
        print("commentaire ignoré (pas du propriétaire)")
        return 0

    cfg = preferences.load_cfg()
    prefs = preferences.load_prefs()
    cmd = body.lower()
    if cmd.startswith("/prefs"):
        reply = "**Préférences actuelles**\n" + describe(prefs)
    elif cmd.startswith("/reset"):
        refused = prefs["refused_issues"]
        prefs = {**preferences.copy.deepcopy(preferences.DEFAULT), "refused_issues": refused}
        _save(preferences.PREFS_PATH, prefs)
        reply = "Préférences remises à zéro."
    else:
        deal = next((d for d in _load(DEALS, {"deals": []}).get("deals", []) if d.get("issue") == number), None)
        new, msgs = preferences.learn(prefs, body, deal, cfg)
        if number and number not in new["refused_issues"]:
            new["refused_issues"] = (new["refused_issues"] + [number])[-300:]
        _save(preferences.PREFS_PATH, new)
        log = _load(LOG, [])
        log.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "issue": number,
                    "text": body[:500], "changes": msgs})
        _save(LOG, log[-500:])
        if msgs:
            reply = "Compris, j'adapte les prochaines offres :\n" + "\n".join(f"- {m}" for m in msgs)
        else:
            reply = ("Refus enregistré, mais je n'ai pas reconnu la raison. Essaie par exemple : « trop cher », "
                     "« séjour trop court », « trop d'escales », « destination déjà vue », « trop loin », "
                     "« avion pas adapté », « trop touristique ».")
        if not deal:
            reply += "\n\n_(Offre introuvable dans le dashboard : seules les règles générales ont pu être appliquées.)_"
        reply += ("\n\nEffectif dès le prochain scan (15 min max). `/prefs` liste tes réglages, `/reset` les efface.")
    try:
        _api("POST", f"/issues/{number}/comments", {"body": reply})
        if not (cmd.startswith("/prefs") or cmd.startswith("/reset")):
            _api("PATCH", f"/issues/{number}", {"state": "closed", "state_reason": "not_planned"})
    except Exception as e:
        print(f"[feedback] réponse impossible : {e}")
    print(reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
