"""Issues GitHub (une par offre publiée, pour pouvoir refuser). Tout est facultatif : un échec ne plante rien."""
from __future__ import annotations

import json
import os
import urllib.request


def _call(method, path, payload=None):
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{path}", method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "User-Agent": "flight-deals", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def create_issue(deal: dict):
    """-> numéro de l'Issue ou None."""
    star = "💺" if deal["kind"] == "business" else "⭐"
    title = f"{star} {deal['origin_city']} → {deal['dest_city']} {deal['price']} € ({deal['score']}/11)"
    body = (f"deal:{deal['key']}\n\n**{deal['origin_city']} → {deal['dest_city']}**, {deal['depart']} → {deal['return']}\n"
            f"Prix du vol (bagages compris) : {deal['flight_price']} €\n\nPour refuser : commente avec la raison.")
    try:
        r = _call("POST", "/issues", {"title": title, "body": body})
        return (r or {}).get("number")
    except Exception:
        return None


def close_issue(number: int, comment: str | None = None):
    try:
        if comment:
            _call("POST", f"/issues/{number}/comments", {"body": comment})
        _call("PATCH", f"/issues/{number}", {"state": "closed"})
    except Exception:
        pass


def comment(number: int, text: str):
    try:
        _call("POST", f"/issues/{number}/comments", {"body": text})
    except Exception:
        pass
