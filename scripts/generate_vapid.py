"""Génère une paire de clés VAPID pour les notifications Web Push.

Usage : python scripts/generate_vapid.py   (nécessite : pip install pywebpush)
La clé PUBLIQUE va dans docs/index.html (constante VAPID_PUBLIC). La clé PRIVÉE ne doit jamais être commitée :
elle va dans le secret GitHub VAPID_PRIVATE_KEY.
"""
import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


v = Vapid()
v.generate_keys()
pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
priv = v.private_key.private_numbers().private_value.to_bytes(32, "big")
print("PUBLIQUE (dans index.html) :", b64(pub))
print("PRIVÉE   (secret GitHub)   :", b64(priv))
