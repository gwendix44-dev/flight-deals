"""Ferme les anciennes Issues d'alerte : python -m flightdeals.cleanup  (lancé à la main, une fois)."""
from __future__ import annotations

import json
import os
import sys
import urllib.request

LABELS = {"erreur-de-prix", "bonne-affaire", "business", "montage-escales"}


def _api(method: str, path: str, payload=None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{path}",
        data=json.dumps(payload).encode() if payload is not None else None, method=method,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "flight-deals"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read() or b"null")


def open_alert_issues() -> list:
    """Numéros de toutes les Issues ouvertes qui sont des alertes de l'appli (jamais les pull requests ni les autres)."""
    numbers, page = [], 1
    while True:
        batch = _api("GET", f"/issues?state=open&per_page=100&page={page}")
        if not batch:
            return numbers
        for it in batch:
            if "pull_request" in it:
                continue
            if LABELS & {l["name"] for l in it.get("labels", [])}:
                numbers.append(it["number"])
        page += 1


def main() -> int:
    numbers = open_alert_issues()
    print(f"{len(numbers)} Issue(s) d'alerte ouverte(s)")
    closed = 0
    for n in numbers:
        try:
            _api("PATCH", f"/issues/{n}", {"state": "closed", "state_reason": "not_planned"})
            closed += 1
        except Exception as e:
            print(f"#{n} : échec ({e})")
    print(f"{closed} fermée(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
