"""Outils communs : fichiers JSON, dates, distances, heure de Paris."""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
PARIS = ZoneInfo("Europe/Paris")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data) -> None:
    """Écriture atomique : un plantage en cours d'écriture ne corrompt jamais l'état."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=False, default=str)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_date(s) -> date | None:
    if not s:
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_dt(s) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def tier(table, km):
    """Table [[limite_km, valeur], ...] triée : valeur du premier palier dont la limite >= km."""
    for limit, value in table:
        if km <= limit:
            return value
    return table[-1][1]


def tier_index(table, km) -> int:
    for i, (limit, _) in enumerate(table):
        if km <= limit:
            return i
    return len(table) - 1


def months_ahead(today: date, n: int) -> list[str]:
    out, y, m = [], today.year, today.month
    for _ in range(n + 1):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def paris_now(utc: datetime | None = None) -> datetime:
    return (utc or now_utc()).astimezone(PARIS)
