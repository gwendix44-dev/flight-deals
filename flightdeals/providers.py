"""Sources de prix. Toutes gratuites, sans dépendance externe."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Iterable

from .airports import DEST_KEYWORDS, ORIGIN_KEYWORDS, ORIGINS, coords
from .core import Leg, Offer, estimate_hours, haversine_km

UA = "personal-flight-deals/1.0"


def _get(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _d(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date() if s else None
    except ValueError:
        return None


# ---------------------------------------------------------------- Travelpayouts
def travelpayouts(origins: Iterable[str], months: list[str], token: str, sleep: float = 0.3) -> list[Offer]:
    """API Data d'Aviasales (gratuite, prix en cache). Une requête par origine et par mois.

    `unique=true` sans destination renvoie le prix le plus bas par destination.
    """
    out: list[Offer] = []
    for org in origins:
        for month in months:
            qs = urllib.parse.urlencode({
                "origin": org, "departure_at": month, "one_way": "false", "unique": "true",
                "sorting": "price", "currency": "eur", "limit": 1000, "token": token,
            })
            try:
                data = json.loads(_get(f"https://api.travelpayouts.com/aviasales/v3/prices_for_dates?{qs}"))
            except Exception as e:  # réseau / quota : on continue avec le reste
                print(f"[travelpayouts] {org} {month}: {e}")
                continue
            for it in data.get("data", []):
                link = it.get("link") or ""
                out.append(Offer(
                    origin=org,
                    dest=it.get("destination", ""),
                    price_eur=float(it.get("price", 0)),
                    depart=_d(it.get("departure_at")),
                    return_date=_d(it.get("return_at")),
                    transfers=int(it.get("transfers") or 0) + int(it.get("return_transfers") or 0) // 2,
                    airline=it.get("airline", ""),
                    duration_min=it.get("duration_to") or None,
                    link="https://www.aviasales.com" + link if link.startswith("/") else link,
                    source="travelpayouts",
                ))
            time.sleep(sleep)
    return out


def exact_price(origin: str, dest: str, depart: date, ret: date | None, token: str, direct: bool | None = None):
    """Prix le plus bas pour CES dates précises (aller-retour si `ret`, sinon aller simple).

    Retourne le prix, ou None si aucun billet n'existe à ces dates. Lève une exception si l'API est injoignable
    (l'appelant écarte alors l'offre plutôt que de l'afficher sans contrôle).
    """
    q = {"origin": origin, "destination": dest, "departure_at": depart.isoformat(), "one_way": "false" if ret else "true",
         "unique": "false", "sorting": "price", "currency": "eur", "limit": 20, "token": token}
    if ret:
        q["return_at"] = ret.isoformat()
    if direct is not None:
        q["direct"] = str(direct).lower()
    data = json.loads(_get("https://api.travelpayouts.com/aviasales/v3/prices_for_dates?" + urllib.parse.urlencode(q)))
    prices = []
    for it in data.get("data", []):
        d1, d2 = _d(it.get("departure_at")), _d(it.get("return_at"))
        if d1 == depart and (not ret or d2 == ret) and it.get("price"):
            prices.append(float(it["price"]))
    return min(prices) if prices else None


def _dt(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


def oneway_legs(origin: str, months: list, token: str, destination: str | None = None,
                direct: bool = True, unique: bool = True, limit: int = 1000, sleep: float = 0.25) -> list:
    """Billets aller simple (Travelpayouts). Sans destination : le moins cher vers chaque destination, par mois."""
    out: list[Leg] = []
    for month in months:
        q = {"origin": origin, "departure_at": month, "one_way": "true", "unique": str(unique).lower(),
             "direct": str(direct).lower(), "sorting": "price", "currency": "eur", "limit": limit, "token": token}
        if destination:
            q["destination"] = destination
        try:
            data = json.loads(_get("https://api.travelpayouts.com/aviasales/v3/prices_for_dates?" + urllib.parse.urlencode(q)))
        except Exception as e:
            print(f"[oneway] {origin}->{destination or '*'} {month}: {e}")
            continue
        for it in data.get("data", []):
            dep = _dt(it.get("departure_at"))
            dest = it.get("destination", "")
            if not dep or not dest or not it.get("price"):
                continue
            dur = it.get("duration_to") or it.get("duration") or 0
            if not dur and coords(origin) and coords(dest):
                dur = int(estimate_hours(haversine_km(*coords(origin), *coords(dest)), int(it.get("transfers") or 0)) * 60)
            link = it.get("link") or ""
            out.append(Leg(orig=origin, dest=dest, dep=dep, dur_min=int(dur), price=float(it["price"]),
                           airline=it.get("airline", ""), transfers=int(it.get("transfers") or 0),
                           link="https://www.aviasales.com" + link if link.startswith("/") else link))
        time.sleep(sleep)
    return out


# ------------------------------------------------------------------------- RSS
PRICE_RE = re.compile(r"(?:€\s?(\d{2,5})|(\d{2,5})\s?(?:€|eur|euros))", re.I)
USD_RE = re.compile(r"\$\s?(\d{2,5})")
ERR_WORDS = ("error fare", "mistake", "erreur", "glitch", "bug")


def parse_deal_title(title: str, link: str = "", source: str = "rss") -> Offer | None:
    t = title.lower()
    m = PRICE_RE.search(title)
    price = None
    if m:
        price = float(m.group(1) or m.group(2))
    else:
        mu = USD_RE.search(title)
        if mu:
            price = float(mu.group(1)) * 0.92  # conversion approximative
    if not price:
        return None
    origin = next((code for kw, code in ORIGIN_KEYWORDS.items() if kw in t.split(" to ")[0] or kw in t.split(" à ")[0]), None)
    if not origin or origin not in ORIGINS:
        return None
    rest = t.split(" to ", 1)[-1] if " to " in t else t.split(" à ", 1)[-1]
    # on cherche le mot-clé le plus long (ex. "new york" avant "york")
    dest = next((DEST_KEYWORDS[k] for k in sorted(DEST_KEYWORDS, key=len, reverse=True) if k in rest), None)
    if not dest:
        return None
    cabin = "business" if ("business" in t or "première" in t) else "economy"
    if "one way" in t or "aller simple" in t:
        return None  # on ne traite que les A/R
    return Offer(origin=origin, dest=dest, price_eur=price, cabin=cabin, link=link,
                 source=source, title=title, flagged_error=any(w in t for w in ERR_WORDS))


def _rss_items(raw: str) -> list:
    """(titre, lien) de chaque <item>. XML strict d'abord, sinon extraction tolérante (flux mal formés)."""
    try:
        root = ET.fromstring(raw)
        return [((i.findtext("title") or "").strip(), (i.findtext("link") or "").strip()) for i in root.iter("item")]
    except ET.ParseError:
        import html
        items = []
        for blk in re.findall(r"<item\b.*?</item>", raw, re.S | re.I):
            t = re.search(r"<title[^>]*>(.*?)</title>", blk, re.S | re.I)
            l = re.search(r"<link[^>]*>(.*?)</link>", blk, re.S | re.I)
            if t:
                clean = lambda x: html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", x)).strip()
                items.append((clean(t.group(1)), clean(l.group(1)) if l else ""))
        return items


def rss(feeds: list[str]) -> list[Offer]:
    out: list[Offer] = []
    for url in feeds:
        try:
            raw = _get(url).decode("utf-8", "replace")
        except Exception as e:
            print(f"[rss] {url}: {e}")
            continue
        for title, link in _rss_items(raw):
            o = parse_deal_title(title, link, source=f"rss:{urllib.parse.urlparse(url).netloc}")
            if o:
                out.append(o)
    return out


# ------------------------------------------------------------------------ Démo
def demo_offers(today: date) -> list[Offer]:
    from datetime import timedelta
    d = lambda n: today + timedelta(days=n)
    return [
        Offer("CDG", "TYO", 489, depart=d(60), return_date=d(75), source="demo", link="https://example.org/1"),
        Offer("CDG", "BKK", 279, depart=d(50), return_date=d(70), transfers=1, source="demo", link="https://example.org/2"),
        Offer("ORY", "SGN", 249, depart=d(80), return_date=d(100), transfers=1, source="demo", link="https://example.org/3",
              flagged_error=True),
        Offer("AMS", "NYC", 215, depart=d(30), return_date=d(40), source="demo", link="https://example.org/4"),
        Offer("MAD", "BOG", 760, cabin="business", depart=d(45), return_date=d(60), source="demo", link="https://example.org/5"),
        Offer("CDG", "SYD", 650, depart=d(40), return_date=d(60), transfers=1, source="demo"),  # trop cher
    ]
