"""Sources de prix gratuites : API Travelpayouts/Aviasales (cache de moteurs) + flux RSS de bons plans."""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from .model import Offer
from .util import parse_date, parse_dt
from .world import dest_code, world

UA = "personal-flight-deals/2.0"
API = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates?"


def http_get(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _api(params: dict, token: str) -> list[dict]:
    q = dict(params, currency="eur", token=token)
    return json.loads(http_get(API + urllib.parse.urlencode(q))).get("data", [])


# ------------------------------------------------------------------ Travelpayouts
def fetch_roundtrips(origins, months, token, errors: list, fetch=None) -> list[Offer]:
    """Prix le plus bas par destination, par origine et par mois (aller-retour)."""
    pause = 0.15 if fetch is None else 0  # pas de pause avec une source simulée (tests)
    fetch = fetch or _api
    jobs = [(o, m) for o in origins for m in months]

    def one(job):
        org, month = job
        try:
            rows = fetch({"origin": org, "departure_at": month, "one_way": "false", "unique": "true",
                          "sorting": "price", "limit": 1000}, token)
            time.sleep(pause)
            return org, rows, None
        except Exception as e:  # réseau, quota, jeton : on continue avec le reste
            return org, [], f"{org} {month}: {type(e).__name__}"

    out: list[Offer] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for org, rows, err in pool.map(one, jobs):
            if err:
                errors.append(err)
            for it in rows:
                dest = dest_code(it.get("destination", "")) or dest_code(it.get("destination_airport", ""))
                price = it.get("price")
                if not dest or not price:
                    continue
                link = it.get("link") or ""
                out.append(Offer(
                    origin=org, dest=dest, price=float(price), depart=parse_date(it.get("departure_at")),
                    return_date=parse_date(it.get("return_at")),
                    transfers=max(int(it.get("transfers") or 0), int(it.get("return_transfers") or 0)),
                    airline=it.get("airline", ""), dest_airport=it.get("destination_airport", ""),
                    flight_number=str(it.get("flight_number") or ""),
                    link="https://www.aviasales.com" + link if link.startswith("/") else link))
    return out


def exact_price(origin, dest_airports, depart: date, ret: date | None, token, fetch=None):
    """Prix le plus bas pour CES dates précises ; None si le billet a disparu. Lève si l'API est injoignable."""
    fetch = fetch or _api
    best = None
    for ap in dest_airports:
        q = {"origin": origin, "destination": ap, "departure_at": depart.isoformat(),
             "one_way": "false" if ret else "true", "unique": "false", "sorting": "price", "limit": 20}
        if ret:
            q["return_at"] = ret.isoformat()
        for it in fetch(q, token):
            if parse_date(it.get("departure_at")) == depart and (not ret or parse_date(it.get("return_at")) == ret) and it.get("price"):
                p = float(it["price"])
                best = p if best is None else min(best, p)
    return best


def fetch_oneways(origin, token, months, destination=None, direct=True, unique=True, limit=1000, fetch=None) -> list[dict]:
    """Billets aller simple : [{dest, dep(datetime aware), dur_min, price, airline, link}]."""
    fetch = fetch or _api
    out = []
    for month in months:
        q = {"origin": origin, "departure_at": month, "one_way": "true", "unique": str(unique).lower(),
             "direct": str(direct).lower(), "sorting": "price", "limit": limit}
        if destination:
            q["destination"] = destination
        try:
            rows = fetch(q, token)
        except Exception:
            continue
        for it in rows:
            dep = parse_dt(it.get("departure_at"))
            if dep and it.get("price") and it.get("destination"):
                link = it.get("link") or ""
                out.append({"dest": it["destination"], "dep": dep, "dur_min": int(it.get("duration_to") or it.get("duration") or 0),
                            "price": float(it["price"]), "airline": it.get("airline", ""),
                            "link": "https://www.aviasales.com" + link if link.startswith("/") else link})
    return out


# ---------------------------------------------------------------------------- RSS
PRICE_RE = re.compile(r"(?:€\s?(\d{2,5})|(\d{2,5})\s?(?:€|eur\b|euros?\b))", re.I)
USD_RE = re.compile(r"\$\s?(\d{2,5})")
ERR_WORDS = ("error fare", "mistake", "erreur", "glitch", "bug")


def parse_deal_title(title: str, link: str = "", source: str = "rss") -> Offer | None:
    t = title.lower()
    m = PRICE_RE.search(title)
    if m:
        price = float(m.group(1) or m.group(2))
    else:
        mu = USD_RE.search(title)
        if not mu:
            return None
        price = float(mu.group(1)) * 0.92
    if "one way" in t or "one-way" in t or "aller simple" in t:
        return None
    sep = " to " if " to " in t else (" à " if " à " in t else None)
    if not sep:
        return None
    head, rest = t.split(sep, 1)
    w = world()
    origin = next((c for kw, c in w["origin_keywords"].items() if kw in head), None)
    if not origin:
        return None
    dest_kw = {**w["dest_keywords"]}
    code = next((dest_kw[k] for k in sorted(dest_kw, key=len, reverse=True) if k in rest), None)
    if not code:
        return None
    cabin = "business" if ("business" in t or "première" in t or "first class" in t) else "economy"
    return Offer(origin=origin, dest=code, price=price, cabin=cabin, link=link, source=source, title=title,
                 flagged_error=any(x in t for x in ERR_WORDS))


def rss_items(raw: str) -> list[tuple[str, str]]:
    try:
        root = ET.fromstring(raw)
        return [((i.findtext("title") or "").strip(), (i.findtext("link") or "").strip()) for i in root.iter("item")]
    except ET.ParseError:
        items = []
        clean = lambda x: html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", x)).strip()
        for blk in re.findall(r"<item\b.*?</item>", raw, re.S | re.I):
            t = re.search(r"<title[^>]*>(.*?)</title>", blk, re.S | re.I)
            l = re.search(r"<link[^>]*>(.*?)</link>", blk, re.S | re.I)
            if t:
                items.append((clean(t.group(1)), clean(l.group(1)) if l else ""))
        return items


def fetch_rss(feeds, errors: list, get=None) -> list[Offer]:
    get = get or http_get
    out = []
    for url in feeds:
        try:
            raw = get(url).decode("utf-8", "replace")
        except Exception as e:
            errors.append(f"rss {urllib.parse.urlparse(url).netloc}: {type(e).__name__}")
            continue
        for title, link in rss_items(raw):
            o = parse_deal_title(title, link, source="rss:" + urllib.parse.urlparse(url).netloc)
            if o:
                out.append(o)
    return out
