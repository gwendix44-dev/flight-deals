"""Créneaux de publication (12h et 19h, heure de Paris).

GitHub Actions ne connaît que l'UTC : on calcule l'heure de Paris soi-même (heure d'été de l'UE : du dernier dimanche de
mars au dernier dimanche d'octobre, 01h UTC). Les scans tournent toutes les 15 min ; le premier scan qui tombe dans la
fenêtre d'un créneau (12h00-15h00, 19h00-22h00) le publie, une seule fois. Un scan retardé par GitHub rattrape donc le créneau.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional


def _last_sunday(y: int, m: int) -> date:
    d = date(y, m, 31)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    return d


def paris_offset_hours(now_utc: datetime) -> int:
    y = now_utc.year
    start = datetime.combine(_last_sunday(y, 3), time(1), tzinfo=timezone.utc)
    end = datetime.combine(_last_sunday(y, 10), time(1), tzinfo=timezone.utc)
    return 2 if start <= now_utc < end else 1


def local_now(now_utc: Optional[datetime] = None) -> datetime:
    """Heure de Paris, sans fuseau (naïve)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    return (now_utc + timedelta(hours=paris_offset_hours(now_utc))).replace(tzinfo=None)


def due_slot(cfg: dict, published: list, now_utc: Optional[datetime] = None) -> Optional[str]:
    """Identifiant du créneau à publier maintenant (ex. '2026-11-07@12:00'), ou None."""
    pub, now = cfg["publication"], local_now(now_utc)
    for hhmm in pub["slots"]:
        h, m = map(int, hhmm.split(":"))
        start = datetime.combine(now.date(), time(h, m))
        sid = f"{now.date().isoformat()}@{hhmm}"
        if start <= now < start + timedelta(minutes=pub["window_minutes"]) and sid not in published:
            return sid
    return None


def next_slot_label(cfg: dict, now_utc: Optional[datetime] = None) -> str:
    pub, now = cfg["publication"], local_now(now_utc)
    for hhmm in pub["slots"]:
        h, m = map(int, hhmm.split(":"))
        if datetime.combine(now.date(), time(h, m)) > now:
            return f"aujourd'hui {hhmm}"
    return f"demain {pub['slots'][0]}"
