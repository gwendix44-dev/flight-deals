"""Notifications natives (Web Push) : aucune appli externe sur le téléphone."""
from __future__ import annotations

import json
import os

SITE = "https://gwendix44-dev.github.io/flight-deals/"


def send_push(title: str, body: str, tag: str = "flight-deals", url: str = "./?fresh=1", sender=None) -> bool:
    """Envoie une notification. Renvoie False (sans planter) si la configuration manque ou si l'envoi échoue."""
    key, sub = os.environ.get("VAPID_PRIVATE_KEY", "").strip(), os.environ.get("PUSH_SUBSCRIPTION", "").strip()
    if not key or not sub:
        print("[push] non configuré (VAPID_PRIVATE_KEY / PUSH_SUBSCRIPTION absents)")
        return False
    try:
        subscription = json.loads(sub)
        payload = json.dumps({"title": title, "body": body, "tag": tag, "url": url}, ensure_ascii=False)
        send = sender
        if send is None:
            from pywebpush import webpush
            send = lambda **kw: webpush(**kw)
        send(subscription_info=subscription, data=payload, vapid_private_key=key,
             vapid_claims={"sub": "mailto:flight-deals@users.noreply.github.com"}, ttl=3600)
        return True
    except Exception as e:
        print(f"[push] échec : {type(e).__name__}: {str(e)[:200]}")
        return False


def slot_message(label: str, standard: list, business: list):
    """(titre, corps) d'une notification groupée de créneau."""
    n = len(standard) + len(business)
    if n == 0:
        return f"{label} : rien d'exceptionnel", "Aucune offre n'atteint 8/10. Détails dans l'appli."
    parts = [f"{d['origin_city']}→{d['dest_city']} {d['price']} €" for d in (standard + business)[:3]]
    return f"{label} : {n} offre{'s' if n > 1 else ''}", " · ".join(parts)
