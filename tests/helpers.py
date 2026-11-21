import json
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from flightdeals import feedback, history, main, prefs, publish
from flightdeals.util import read_json

RAW = read_json(Path(__file__).resolve().parent.parent / "config.json")
CFG = prefs.effective(RAW, prefs.DEFAULT)
TODAY = date(2026, 11, 21)


def sandbox():
    """Redirige tous les fichiers d'état vers un dossier temporaire."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "data").mkdir()
    (tmp / "docs").mkdir()
    ps = [
        mock.patch.object(publish, "STATE", tmp / "data/publish_state.json"),
        mock.patch.object(publish, "WATCH", tmp / "data/watch.json"),
        mock.patch.object(publish, "DEALS", tmp / "docs/deals.json"),
        mock.patch.object(history, "PATH", tmp / "data/history.json"),
        mock.patch.object(main, "STATUS", tmp / "docs/status.json"),
        mock.patch.object(prefs, "PATH", tmp / "docs/preferences.json"),
        mock.patch.object(feedback, "ROOT", tmp),
        mock.patch.object(feedback, "DEALS", tmp / "docs/deals.json"),
    ]
    for p in ps:
        p.start()
    return tmp, ps


def stop(ps):
    for p in ps:
        p.stop()


def fake_fetch(rows_by_origin):
    """Faux API Travelpayouts : {origine: [ligne,...]} ; répond aussi aux revérifications de dates exactes."""
    def fetch(params, token):
        rows = rows_by_origin.get(params["origin"], [])
        if params.get("destination"):
            rows = [r for r in rows if r["destination"] == params["destination"] or r.get("destination_airport") == params["destination"]]
        return rows
    return fetch


def row(dest, price, days_out=40, stay=14, airline="KL", transfers=0):
    d = TODAY + timedelta(days=days_out)
    return {"destination": dest, "price": price, "departure_at": d.isoformat() + "T10:00:00+01:00",
            "return_at": (d + timedelta(days=stay)).isoformat() + "T10:00:00+01:00", "airline": airline,
            "transfers": transfers, "return_transfers": transfers, "link": "/search/x"}


def noon(day=TODAY, hh=11, mm=10):
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=timezone.utc)
