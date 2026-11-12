"""Traite un refus : python -m flightdeals.feedback

Deux façons de refuser (le workflow .github/workflows/feedback.yml se déclenche dans les deux cas) :
  * une NOUVELLE Issue « Refus : … » créée par le bouton « Refuser » du dashboard (corps : `deal:<clé>`, `issue:<n>`, `---`,
    puis ta raison) ;
  * un COMMENTAIRE de ta part sur l'Issue d'une offre.
Dans les deux cas : ta raison est apprise (docs/preferences.json), l'offre est inscrite comme refusée (les scans la retirent
du dashboard et de la réserve et ne la republient jamais), et les Issues concernées sont fermées.

Variables d'environnement : EVENT_NAME, COMMENT_BODY, COMMENT_USER, ISSUE_TITLE, ISSUE_BODY, ISSUE_USER, ISSUE_NUMBER,
GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_REPOSITORY_OWNER. Sécurité : seul le propriétaire du dépôt est écouté (dépôt public).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Optional

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
    rows.append(f"{len(p.get('refused_keys', []))} offre(s) refusée(s) définitivement")
    return "\n".join(f"- {r}" for r in rows)


def parse_refusal_issue(title: str, body: str) -> Optional[dict]:
    """Issue « Refus : … » créée par le dashboard -> {key, issue, reason}. None si ce n'est pas un refus."""
    if not (title or "").strip().lower().startswith("refus"):
        return None
    body = body or ""
    key = re.search(r"^deal:([0-9a-f]{6,40})\s*$", body, re.M)
    num = re.search(r"^issue:(\d+)\s*$", body, re.M)
    reason = body.split("\n---", 1)[1].strip() if "\n---" in body else re.sub(r"^(deal|issue):.*$", "", body, flags=re.M).strip()
    return {"key": key.group(1) if key else "", "issue": int(num.group(1)) if num else 0, "reason": reason}


def find_deal(key: str, issue: int) -> Optional[dict]:
    deals = _load(DEALS, {"deals": []}).get("deals", [])
    for d in deals:
        if key and d.get("key") == key:
            return d
    for d in deals:
        if issue and d.get("issue") == issue:
            return d
    return None


def refuse(prefs: dict, key: str, issue: int) -> dict:
    """Inscrit l'offre comme refusée pour de bon (les scans la retirent partout et ne la republient jamais)."""
    if key and key not in prefs["refused_keys"]:
        prefs["refused_keys"] = (prefs["refused_keys"] + [key])[-500:]
    if issue and issue not in prefs["refused_issues"]:
        prefs["refused_issues"] = (prefs["refused_issues"] + [issue])[-500:]
    return prefs


def main() -> int:
    env = os.environ.get
    owner = env("GITHUB_REPOSITORY_OWNER", "")
    event = env("EVENT_NAME", "issue_comment")
    if event == "issues":
        user, number = env("ISSUE_USER", ""), int(env("ISSUE_NUMBER", "0") or 0)
        ref = parse_refusal_issue(env("ISSUE_TITLE", ""), env("ISSUE_BODY", ""))
        body = (ref or {}).get("reason", "")
    else:
        user, number = env("COMMENT_USER", ""), int(env("ISSUE_NUMBER", "0") or 0)
        ref, body = None, (env("COMMENT_BODY") or "").strip()
    if (event == "issues" and not ref) or not body and not ref or user.lower() != owner.lower() or user.endswith("[bot]"):
        print("événement ignoré (pas un refus du propriétaire)")
        return 0

    cfg = preferences.load_cfg()
    prefs = preferences.load_prefs()
    cmd = body.lower()
    close_numbers: list = []
    if event != "issues" and cmd.startswith("/prefs"):
        reply = "**Préférences actuelles**\n" + describe(prefs)
    elif event != "issues" and cmd.startswith("/reset"):
        keep = {k: prefs[k] for k in ("refused_issues", "refused_keys")}
        prefs = {**preferences.copy.deepcopy(preferences.DEFAULT), **keep}
        _save(preferences.PREFS_PATH, prefs)
        reply = "Préférences remises à zéro (les offres déjà refusées restent refusées)."
    else:
        key, target = (ref["key"], ref["issue"]) if ref else ("", number)
        deal = find_deal(key, target)
        if deal:
            key = key or deal.get("key", "")
            target = target or deal.get("issue") or 0
        new, msgs = preferences.learn(prefs, body, deal, cfg)
        refuse(new, key, target)
        _save(preferences.PREFS_PATH, new)
        log = _load(LOG, [])
        log.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "issue": target, "key": key,
                    "text": body[:500], "changes": msgs})
        _save(LOG, log[-500:])
        if msgs:
            reply = "Compris, j'adapte les prochaines offres :\n" + "\n".join(f"- {m}" for m in msgs)
        else:
            reply = ("Refus enregistré, mais je n'ai pas reconnu la raison. Essaie par exemple : « trop cher », "
                     "« séjour trop court », « trop d'escales », « destination déjà vue », « trop loin », "
                     "« avion pas adapté », « trop touristique ».")
        reply += "\n\n✔ **L'offre est supprimée** : elle disparaît du dashboard au prochain scan et ne sera plus jamais proposée."
        if not deal:
            reply += "\n\n_(Offre introuvable dans le dashboard : seules les règles générales ont pu être appliquées.)_"
        reply += "\n\nEffectif dès le prochain scan. `/prefs` liste tes réglages, `/reset` les efface."
        close_numbers = [n for n in {number if event == "issues" else 0, target} if n]
        if event != "issues" and number:
            close_numbers = [number]
    try:
        _api("POST", f"/issues/{number}/comments", {"body": reply})
        for n in close_numbers:
            _api("PATCH", f"/issues/{n}", {"state": "closed", "state_reason": "not_planned"})
    except Exception as e:
        print(f"[feedback] réponse impossible : {e}")
    print(reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
