"""Données du monde : aéroports, destinations, régions, rareté."""
from __future__ import annotations

from functools import lru_cache

from .util import ROOT, haversine_km, read_json


@lru_cache(maxsize=1)
def world() -> dict:
    return read_json(ROOT / "data" / "world.json", {})


@lru_cache(maxsize=1)
def _airport_to_city() -> dict:
    m = {}
    for code, d in world()["destinations"].items():
        m[code] = code
        for ap in d.get("airports", []):
            m[ap] = code
    return m


def dest_code(code: str):
    """Code IATA (aéroport ou ville) -> code de destination connue, sinon None."""
    return _airport_to_city().get(code)


def coords(code: str):
    w = world()
    for table in ("origins", "destinations", "hubs"):
        if code in w[table]:
            d = w[table][code]
            return d["lat"], d["lon"]
    return None


def distance_km(a: str, b: str):
    ca, cb = coords(a), coords(b)
    return round(haversine_km(*ca, *cb)) if ca and cb else None


def city(code: str) -> str:
    w = world()
    for table in ("destinations", "origins", "hubs"):
        if code in w[table]:
            return w[table][code]["city"]
    return code


def country(code: str) -> str:
    d = world()["destinations"].get(code) or world()["hubs"].get(code)
    return d["country"] if d else ""


def region_of(cc: str) -> str:
    for r, ccs in world()["regions"].items():
        if cc in ccs:
            return r
    return "autre"


def secrecy(code: str) -> float:
    w = world()
    if code in w["mainstream"]:
        return 0.0
    if code in w["known"]:
        return 0.5
    if code in w["offbeat"]:
        return 1.5
    return 1.0


def dest_airports(code: str) -> list[str]:
    d = world()["destinations"].get(code)
    return (d["airports"] or [code]) if d else [code]
