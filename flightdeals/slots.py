"""Créneaux de publication 12h00 et 19h00, heure de Paris (heure d'été gérée par zoneinfo)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .util import PARIS


def slot_times(day, cfg):
    """Datetimes (UTC) des créneaux d'un jour calendaire de Paris."""
    out = []
    for hhmm in cfg["publication"]["slots"]:
        h, m = map(int, hhmm.split(":"))
        local = datetime(day.year, day.month, day.day, h, m, tzinfo=PARIS)
        out.append((f"{day.isoformat()}@{hhmm}", local.astimezone(timezone.utc)))
    return out


def due_slot(now_utc: datetime, done: dict, cfg):
    """Créneau à publier maintenant : le plus récent déjà passé, pas encore fait, rattrapé jusqu'à 3 h après."""
    today = now_utc.astimezone(PARIS).date()
    cands = []
    for d in (today - timedelta(days=1), today):
        cands += slot_times(d, cfg)
    cands.sort(key=lambda x: x[1])
    catch = timedelta(hours=cfg["publication"]["catch_up_hours"])
    ok = [(sid, t) for sid, t in cands if t <= now_utc <= t + catch and sid not in done]
    return ok[-1] if ok else None


def next_slot(now_utc: datetime, cfg):
    today = now_utc.astimezone(PARIS).date()
    for d in (today, today + timedelta(days=1)):
        for sid, t in slot_times(d, cfg):
            if t > now_utc:
                local = t.astimezone(PARIS)
                label = ("aujourd'hui " if local.date() == today else "demain ") + local.strftime("%H:%M")
                return sid, t, label
    return None
