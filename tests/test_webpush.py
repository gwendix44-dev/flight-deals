import base64
import json
import os
import unittest

try:
    import http_ece
    import pywebpush
    import requests
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from py_vapid import Vapid
    HAVE = True
except ImportError:          # pywebpush absent de cette machine : ces tests tournent sur GitHub (pip install -r requirements.txt)
    HAVE = False

from flightdeals import webpush


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@unittest.skipUnless(HAVE, "pywebpush non installé")
class RealEncryption(unittest.TestCase):
    """Un faux téléphone (clés P-256) reçoit un vrai message chiffré et le déchiffre, comme le ferait le navigateur."""

    def setUp(self):
        self.phone = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        pub = self.phone.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.sub = {"endpoint": "https://push.example/send/abc", "keys": {"p256dh": b64(pub), "auth": b64(self.auth)}}
        v = Vapid()
        v.generate_keys()
        self.vapid_pub = b64(v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        self.vapid_priv = b64(v.private_key.private_numbers().private_value.to_bytes(32, "big"))
        self.calls = []
        self.old_post = requests.post
        self.status = 201

        def fake_post(url, data=None, headers=None, timeout=None, **kw):
            self.calls.append((url, data, headers))
            r = requests.Response()
            r.status_code = self.status
            r._content = b""
            return r
        requests.post = fake_post
        self.old_env = dict(os.environ)
        os.environ["VAPID_PRIVATE_KEY"] = self.vapid_priv
        os.environ["PUSH_SUBSCRIPTION"] = json.dumps(self.sub)
        os.environ["GITHUB_REPOSITORY"] = "Moi/flight-deals"

    def tearDown(self):
        requests.post = self.old_post
        os.environ.clear()
        os.environ.update(self.old_env)

    def test_message_is_encrypted_signed_and_decryptable(self):
        n = webpush.send({"title": "✈️ Publication de 12h", "body": "3 deals", "url": "https://x/?fresh=1"})
        self.assertEqual(n, 1)
        url, body, headers = self.calls[0]
        self.assertEqual(url, self.sub["endpoint"])
        clear = http_ece.decrypt(body, private_key=self.phone, auth_secret=self.auth)        # ce que lit le téléphone
        self.assertEqual(json.loads(clear.decode())["title"], "✈️ Publication de 12h")
        self.assertNotIn(b"Publication", body)                                                # rien n'est lisible en transit
        h = {k.lower(): v for k, v in headers.items()}
        self.assertIn("vapid", h["authorization"].lower())
        self.assertIn(self.vapid_pub, h["authorization"])                                      # signé avec NOTRE clé
        self.assertEqual(h["content-encoding"], "aes128gcm")
        self.assertEqual(h.get("urgency"), "high")

    def test_expired_subscription_is_reported_not_fatal(self):
        self.status = 410
        self.assertEqual(webpush.send({"title": "t", "body": "b"}), 0)

    def test_notify_uses_native_push(self):
        from datetime import date, timedelta
        import copy
        from flightdeals import evaluate, notify
        from flightdeals.core import Offer
        cfg = json.loads(open(os.path.join(os.path.dirname(__file__), "..", "config.json")).read())
        cfg["scoring"]["min_score"] = 0
        cfg["scoring"]["require_anomaly"] = False
        t = date.today()
        v = evaluate.evaluate(Offer("CDG", "ALA", 200, depart=t + timedelta(days=60), return_date=t + timedelta(days=75),
                                    transfers=0, source="travelpayouts"), cfg, {}, evaluate.load_budgets(), t)
        os.environ.pop("NTFY_TOPIC", None)
        out = notify.send_push_summary([v], "Publication de 12h")
        self.assertEqual(out, [v])
        clear = json.loads(http_ece.decrypt(self.calls[0][1], private_key=self.phone, auth_secret=self.auth).decode())
        self.assertIn("Publication de 12h", clear["title"])
        self.assertEqual(clear["url"], "https://moi.github.io/flight-deals/?fresh=1")
        self.assertIn("Almaty", clear["body"])


class Config(unittest.TestCase):
    def setUp(self):
        self.old = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old)

    def test_not_configured_means_nothing_sent(self):
        for k in ("VAPID_PRIVATE_KEY", "PUSH_SUBSCRIPTION"):
            os.environ.pop(k, None)
        self.assertFalse(webpush.configured())
        self.assertEqual(webpush.send({"title": "x"}), 0)

    def test_subscription_parsing(self):
        os.environ["PUSH_SUBSCRIPTION"] = "pas du json"
        self.assertEqual(webpush.subscriptions(), [])
        os.environ["PUSH_SUBSCRIPTION"] = json.dumps({"endpoint": "https://a", "keys": {"p256dh": "x", "auth": "y"}})
        self.assertEqual(len(webpush.subscriptions()), 1)
        os.environ["PUSH_SUBSCRIPTION"] = json.dumps([{"endpoint": "https://a", "keys": {"p256dh": "x", "auth": "y"}}, {"foo": 1}])
        self.assertEqual(len(webpush.subscriptions()), 1)            # le téléphone ET un éventuel second appareil


if __name__ == "__main__":
    unittest.main()
