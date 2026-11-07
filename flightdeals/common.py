"""Outils partagés : fichiers JSON, empreinte d'une offre, mois à scanner."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def months_ahead(n: int, today: date) -> list[str]:
    out, y, m = [], today.year, today.month
    for _ in range(n + 1):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def dedupe_key(o) -> str:
    raw = f"{o.origin}|{o.dest}|{o.cabin}|{o.depart}|{o.return_date}|{o.title}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]
