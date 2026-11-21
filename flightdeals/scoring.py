"""Note sur 11 : 6 critères (10 max) + bonus erreur de prix (+1)."""
from __future__ import annotations

from statistics import median

from .util import tier
from .world import secrecy


def _lin(x, zero, full):
    """0 à `zero`, 1 à `full` (fonctionne dans les deux sens)."""
    if full == zero:
        return 0.0
    return max(0.0, min(1.0, (x - zero) / (full - zero)))


def benchmark(km: float, cfg: dict, business: bool = False) -> float:
    s = cfg["scoring"]
    b = s["bench_base"] + s["bench_per_km"] * km
    return b * s["business_multiplier"] if business else b


def hist_median(history: dict, origin: str, dest: str, min_obs: int = 5):
    vals = [p for _, p in history.get(f"{origin}-{dest}", [])]
    return median(vals) if len(vals) >= min_obs else None


def score_standard(*, price, km, total, cap, stay_days, stay_min, stay_cost, dest, transfers, aircraft_status,
                   separate_tickets, flagged_error, med, cfg) -> dict:
    s = cfg["scoring"]
    bench = benchmark(km, cfg)
    disc_ref = 1 - price / bench
    disc_hist = (1 - price / med) if med else -9
    disc = max(disc_ref, disc_hist)
    p_price = 3 * _lin(disc, s["price_zero_discount"], s["price_full_discount"])
    p_budget = 2 * _lin(total / cap, 1.0, s["budget_full_share"])
    p_dest = secrecy(dest)
    q = {0: 0.8, 1: 0.5}.get(transfers, 0.2)
    q += 0.7 if aircraft_status in ("widebody", "not_required") else 0.2
    if separate_tickets:
        q -= 0.2
    p_quality = max(0.0, min(1.5, q))
    p_dur = 1.0 if stay_min <= stay_days <= stay_min + cfg["stay"]["ideal_window_days"] else 0.6
    ratio = total / (bench + stay_cost) if (bench + stay_cost) else 1
    p_overall = _lin(ratio, s["overall_ratio_zero"], s["overall_ratio_full"])
    bonus = 1.0 if (flagged_error or (med and price <= med * s["error_history_ratio"])
                    or disc_ref >= s["error_bench_discount"]) else 0.0
    parts = {"Prix": (p_price, 3), "Budget": (p_budget, 2), "Destination": (p_dest, 1.5),
             "Vol": (p_quality, 1.5), "Durée": (p_dur, 1), "Économie globale": (p_overall, 1)}
    total_score = sum(v for v, _ in parts.values()) + bonus
    return {"score": round(min(total_score, s["max"]), 1),
            "detail": {k: [round(v, 1), m] for k, (v, m) in parts.items()},
            "bonus": bonus, "discount": round(disc, 3), "bench": round(bench)}


def score_business(*, price, km, flagged_error, cfg) -> dict:
    s, b = cfg["scoring"], cfg["business"]
    bench = benchmark(km, cfg, business=True)
    disc = 1 - price / bench
    score = s["max"] * max(disc, 0) / b["full_discount"]
    if flagged_error:
        score += 1
    return {"score": round(min(score, s["max"]), 1), "discount": round(disc, 3), "bench": round(bench),
            "bonus": 1.0 if flagged_error else 0.0, "detail": {}}
