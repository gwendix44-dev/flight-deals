"""Refus d'une offre : la raison est lue (mots-clés, gratuit) et durcit les préférences. L'offre est supprimée pour toujours."""
from __future__ import annotations

import os
import re
import unicodedata

from . import github, prefs as P
from .util import ROOT, now_utc, read_json, tier_index, write_json
from .publish import DEALS, STATE, load_state, save_state, write_deals


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).replace("’", "'")


def _round50(x):
    return int(round(x / 50.0) * 50)


def apply_reason(p: dict, reason: str, deal: dict | None, cfg: dict) -> list[str]:
    """Modifie `p` selon la raison. Renvoie la liste des effets, en français."""
    t = norm(reason)
    fx: list[str] = []
    d = deal or {}

    m = re.search(r"max(?:imum)?\s*(\d{3,5})", t)
    if "trop cher" in t or m:
        if d.get("kind") == "business":
            cap = int(m.group(1)) if m else max(300, _round50(d.get("price", 800) * 0.9))
            p["business_cap_eur"] = min(p.get("business_cap_eur") or 10**6, cap)
            fx.append(f"Plafond business abaissé à {p['business_cap_eur']} €.")
        elif d:
            idx = tier_index(cfg["budget_by_distance_km"], d["km"])
            cap = int(m.group(1)) if m else max(600, _round50(d["total"] * 0.9))
            old = (p["cap_by_tier"] or {}).get(str(idx), 10**6)
            p["cap_by_tier"][str(idx)] = min(old, cap)
            fx.append(f"Budget total plafonné à {p['cap_by_tier'][str(idx)]} € pour ce palier de distance.")
    if "sejour trop court" in t or "trop court" in t:
        p["min_stay_extra"] = int(p.get("min_stay_extra") or 0) + 2
        fx.append("Séjour minimum +2 jours.")
    if "sejour trop long" in t and d:
        p["max_stay_days"] = max(5, d["stay_days"] - 1)
        fx.append(f"Séjour limité à {p['max_stay_days']} jours.")
    if "vol trop long" in t and d:
        p["max_flight_hours"] = max(4, d["hours"] - 1)
        fx.append(f"Durée de vol limitée à {p['max_flight_hours']} h.")
    if "trop loin" in t and d:
        p["max_distance_km"] = max(1500, d["km"] - 800)
        fx.append(f"Distance maximale : {p['max_distance_km']} km.")
    if "trop proche" in t and d:
        p["min_distance_km"] = d["km"] + 500
        fx.append(f"Distance minimale : {p['min_distance_km']} km.")
    if "escale" in t and "trop" in t and d:
        p["max_transfers"] = max(0, d["transfers"] - 1)
        fx.append(f"{p['max_transfers']} escale(s) maximum.")
    if any(k in t for k in ("avion pas adapte", "monocouloir", "a320", "a321", "737")):
        p["strict_aircraft"] = True
        fx.append("MODE STRICT AVION : seuls les gros-porteurs confirmés passent.")
    if any(k in t for k in ("billets separes", "risque", "montage")):
        p["stopovers_disabled"] = True
        fx.append("Montages à billets séparés désactivés.")
    if any(k in t for k in ("destination deja vue", "pas interessant", "pas envie")) and d:
        if d["dest"] not in p["excluded_destinations"]:
            p["excluded_destinations"].append(d["dest"])
        fx.append(f"Destination exclue : {d['dest_city']}.")
    if any(k in t for k in ("mauvaise periode", "dates", "vacances")) and d:
        mth = int(d["depart"][5:7])
        if mth not in p["excluded_months"]:
            p["excluded_months"].append(mth)
        fx.append(f"Mois de départ exclu : {mth}.")
    if any(k in t for k in ("trop touristique", "banal", "pas original", "classique")):
        p["min_secrecy"] = 1.5 if p.get("min_secrecy") else 1.0
        fx.append("Destinations plus rares exigées.")
    if any(k in t for k in ("pas assez exceptionnel", "bof")):
        p["min_score_bonus"] = round(min(1.0, float(p.get("min_score_bonus") or 0) + 0.3), 1)
        fx.append(f"Seuil de publication relevé de {p['min_score_bonus']}.")
    return fx


def find_deal(key: str):
    """Retrouve l'offre (publiée, bon plan ou en réserve) pour connaître ses caractéristiques."""
    s = load_state()
    for lst in (s["published"], s["good"], s["reserve"]):
        for d in lst:
            if d["key"] == key:
                return d
    return None


def forget(key: str, state: dict) -> list[int]:
    """Supprime l'offre partout ; renvoie les numéros d'Issues à fermer."""
    issues = []
    for name in ("published", "good", "reserve"):
        keep = []
        for d in state[name]:
            if d["key"] == key:
                if d.get("issue"):
                    issues.append(d["issue"])
            else:
                keep.append(d)
        state[name] = keep
    return issues


def refuse(key: str, reason: str, cfg: dict, issue_numbers=()) -> dict:
    p = P.load()
    state = load_state()
    deal = find_deal(key)
    fx = apply_reason(p, reason, deal, cfg)
    if key and key not in p["refused_keys"]:
        p["refused_keys"].append(key)
    for n in issue_numbers:
        if n and n not in p["refused_issues"]:
            p["refused_issues"].append(n)
    closing = forget(key, state)
    for n in closing:
        if n not in p["refused_issues"]:
            p["refused_issues"].append(n)
    P.save(p)
    save_state(state)
    if DEALS.exists():
        write_deals(state, {k: v for k, v in (read_json(DEALS, {}) or {}).items() if k not in ("updated", "deals", "business", "good")},
                    now_utc(), lambda d: True)
    log = read_json(ROOT / "data" / "feedback.json", []) or []
    log.append({"at": now_utc().isoformat(), "key": key, "text": reason, "changes": fx})
    write_json(ROOT / "data" / "feedback.json", log[-100:])
    return {"effects": fx, "close": sorted(set(closing) | set(issue_numbers)), "recognized": bool(fx)}


def reset() -> None:
    p = P.load()
    fresh = P.load("/nonexistent")
    fresh["refused_keys"], fresh["refused_issues"] = p["refused_keys"], p["refused_issues"]
    P.save(fresh)


def parse_refusal_body(body: str):
    key = re.search(r"deal:\s*([0-9a-f]{8,40})", body or "")
    issue = re.search(r"issue:\s*(\d+)", body or "")
    reason = (body or "").split("---", 1)[1].strip() if "---" in (body or "") else ""
    return (key.group(1) if key else ""), (int(issue.group(1)) if issue else None), reason


def main() -> None:
    from .util import read_json as rj
    cfg = rj(ROOT / "config.json")
    event, num = os.environ.get("EVENT_NAME", ""), int(os.environ.get("ISSUE_NUMBER") or 0)
    title, body, comment = os.environ.get("ISSUE_TITLE", ""), os.environ.get("ISSUE_BODY", ""), os.environ.get("COMMENT_BODY", "")
    if event == "issue_comment":
        text = comment.strip()
        if text.startswith("/prefs"):
            lines = P.describe(P.load()) or ["Aucune préférence apprise."]
            github.comment(num, "**Préférences apprises :**\n- " + "\n- ".join(lines))
            return
        if text.startswith("/reset"):
            reset()
            github.comment(num, "Préférences effacées. Les offres refusées restent refusées.")
            return
        key, _, _ = parse_refusal_body(body)
        res = refuse(key, text, cfg, [num])
    elif event == "issues" and title.lower().startswith("refus"):
        key, ref_issue, reason = parse_refusal_body(body)
        res = refuse(key, reason, cfg, [num, ref_issue])
    elif event == "issues" and title.lower().startswith("commande"):
        cmd = (body or title).strip().split()[0] if (body or title).strip() else ""
        cmd = "/reset" if "/reset" in (body + title) else ("/prefs" if "/prefs" in (body + title) else cmd)
        if cmd == "/reset":
            reset()
            github.comment(num, "Préférences effacées. Les offres refusées restent refusées.")
        else:
            github.comment(num, "**Préférences apprises :**\n- " + "\n- ".join(P.describe(P.load()) or ["Aucune préférence apprise."]))
        github.close_issue(num)
        return
    else:
        print("rien à faire")
        return
    msg = ("Offre supprimée pour toujours. " + (" ".join(res["effects"]) if res["recognized"]
           else "Raison non reconnue : l'offre est supprimée, mais rien d'autre n'a changé."))
    github.comment(num, msg)
    for n in res["close"]:
        github.close_issue(n)


if __name__ == "__main__":
    main()
