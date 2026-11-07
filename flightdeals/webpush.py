"""Notifications natives du raccourci installé sur le téléphone (Web Push), sans aucune appli externe.

Fonctionnement : l'appli (dashboard) demande l'autorisation, le navigateur du téléphone crée un « abonnement » (une adresse
chez Google/Apple + des clés). Ce texte est collé UNE fois dans le secret GitHub PUSH_SUBSCRIPTION. À chaque publication, ce
module chiffre le message avec les clés de l'abonnement, le signe avec la clé privée VAPID (secret VAPID_PRIVATE_KEY) et
l'envoie au service push de Google/Apple, qui réveille le raccourci même si l'appli est fermée.

Test : python -m flightdeals.webpush --test
"""
from __future__ import annotations

import json
import os
import sys


def subscriptions() -> list:
    raw = os.environ.get("PUSH_SUBSCRIPTION", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("[webpush] PUSH_SUBSCRIPTION n'est pas un JSON valide : recopie le texte affiché par l'appli, en entier")
        return []
    data = [data] if isinstance(data, dict) else data
    return [s for s in data if isinstance(s, dict) and s.get("endpoint") and isinstance(s.get("keys"), dict)]


def configured() -> bool:
    return bool(os.environ.get("VAPID_PRIVATE_KEY", "").strip()) and bool(subscriptions())


def _subject() -> str:
    if os.environ.get("VAPID_SUBJECT"):
        return os.environ["VAPID_SUBJECT"]
    # La bibliothèque n'accepte qu'un « mailto: » ou un « https://nom-de-domaine » SANS chemin : on prend le domaine de ta page
    # GitHub Pages, ce qui évite aussi de publier ton email dans un dépôt public.
    owner = os.environ.get("GITHUB_REPOSITORY", "gwendix44-dev/flight-deals").split("/")[0].lower()
    return f"https://{owner}.github.io"


def send(payload: dict, ttl: int = 43200) -> int:
    """Envoie `payload` (title, body, url, tag) à tous les appareils abonnés. Retourne le nombre de livraisons réussies."""
    key, subs = os.environ.get("VAPID_PRIVATE_KEY", "").strip(), subscriptions()
    if not key or not subs:
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        print("[webpush] bibliothèque pywebpush absente (pip install -r requirements.txt)")
        return 0
    ok = 0
    for sub in subs:
        try:
            webpush(subscription_info=sub, data=json.dumps(payload, ensure_ascii=False), vapid_private_key=key,
                    vapid_claims={"sub": _subject()}, ttl=ttl, headers={"Urgency": "high"})
            ok += 1
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):
                print("[webpush] abonnement expiré ou supprimé : réactive les notifications dans l'appli et recolle le texte")
            else:
                print(f"[webpush] échec (HTTP {code}) : {e}")
        except Exception as e:
            print(f"[webpush] échec : {e}")
    return ok


def main() -> int:
    if "--test" not in sys.argv:
        print("usage : python -m flightdeals.webpush --test")
        return 2
    print(f"clé privée VAPID : {'présente' if os.environ.get('VAPID_PRIVATE_KEY', '').strip() else 'ABSENTE (secret VAPID_PRIVATE_KEY)'}")
    print(f"appareils abonnés : {len(subscriptions())}")
    if not configured():
        print("Rien à envoyer : il manque le secret VAPID_PRIVATE_KEY ou PUSH_SUBSCRIPTION.")
        return 1
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    url = f"https://{repo.split('/')[0].lower()}.github.io/{repo.split('/')[1]}/?fresh=1" if "/" in repo else "./"
    n = send({"title": "✅ Flight Deals : les notifications fonctionnent", "body": "Tu recevras ici les deals de 12h et 19h, et les 10/10 tout de suite.",
              "url": url, "tag": "test"})
    print(f"{n} notification(s) envoyée(s)")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
