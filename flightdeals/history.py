"""Historique des prix par route (médiane de référence). Compact : 1 point par jour et par route."""
from __future__ import annotations

from datetime import date

from .util import ROOT, read_json, write_json

PATH = ROOT / "data" / "history.json"
MAX_POINTS = 45


def load() -> dict:
    return read_json(PATH, {}) or {}


def update(history: dict, offers, today: date) -> dict:
    day = int(today.strftime("%Y%m%d"))
    best: dict[str, float] = {}
    for o in offers:
        if o.cabin != "economy" or o.source != "travelpayouts":
            continue
        k = f"{o.origin}-{o.dest}"
        best[k] = min(best.get(k, 1e9), o.price)
    for k, p in best.items():
        pts = history.setdefault(k, [])
        if pts and pts[-1][0] == day:
            pts[-1][1] = min(pts[-1][1], round(p))
        else:
            pts.append([day, round(p)])
        del pts[:-MAX_POINTS]
    return history


def save(h: dict) -> None:
    write_json(PATH, h)
