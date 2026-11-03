"""Raw poll weights (plan §6.2 Steps 1-2) and the per-pollster cap (Step 5)."""
from __future__ import annotations

import re
from datetime import date

import numpy as np
import pandas as pd

from ..config import Polls


def margin_2p(d, r):
    """Two-party margin in points, D-side minus R: 100(d-r)/(d+r)."""
    d, r = np.asarray(d, dtype=float), np.asarray(r, dtype=float)
    return 100.0 * (d - r) / (d + r)


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def ratings_lookup(ratings: pd.DataFrame | None) -> dict[str, float]:
    """pollster_ratings.csv (pollster, rating in [0,3]) -> {normalised name: rating}."""
    if ratings is None or ratings.empty:
        return {}
    return {norm_name(p): float(r) for p, r in zip(ratings.pollster, ratings.rating) if pd.notna(r)}


def w_time(age_days, half_life: float):
    return 2.0 ** (-np.asarray(age_days, dtype=float) / half_life)


def w_sample(n, cfg: Polls):
    """min(sqrt(n/600), 1.5) with n clamped to [n_min, n_cap]; unknown n is treated as n_min."""
    n = pd.Series(n, dtype="float64").fillna(cfg.n_min).clip(cfg.n_min, cfg.n_cap)
    return np.minimum(np.sqrt(n / cfg.n_ref), cfg.n_weight_max).to_numpy()


def w_quality(rating):
    return 0.5 + 0.5 * np.asarray(rating, dtype=float) / 3.0


def poll_weights(polls: pd.DataFrame, as_of: date, kind: str, cfg: Polls,
                 ratings: dict[str, float] | None = None) -> pd.DataFrame:
    """Adds age_days, w_time, w_n, w_q, w_pop, w_typ and the product `w`.

    `kind` is "senate" or "generic" (selects half-life). Expects columns field_end, n, pop, pollster, partisan,
    matchup_type."""
    out = polls.copy()
    ratings = ratings or {}
    hl = getattr(cfg.half_life_days, kind)
    out["age_days"] = (pd.Timestamp(as_of) - pd.to_datetime(out.field_end)).dt.days
    out["w_time"] = w_time(out.age_days, hl)
    out["w_n"] = w_sample(out.n, cfg)
    rating = out.pollster.map(lambda p: ratings.get(norm_name(p), cfg.unrated_rating))
    out["w_q"] = w_quality(rating)
    out["w_pop"] = out["pop"].map(cfg.population_weight.model_dump()).fillna(cfg.population_weight.A)
    typ = np.where(out.partisan.fillna(False).astype(bool), cfg.partisan_weight, 1.0)
    typ = typ * np.where(out.matchup_type.eq("multi"), cfg.multiway_weight, 1.0)
    out["w_typ"] = typ
    out["w"] = out.w_time * out.w_n * out.w_q * out.w_pop * out.w_typ
    return out


def cap_pollster_weights(w: np.ndarray, pollster: np.ndarray, cap: float, cap_few: float,
                         max_iter: int = 10) -> tuple[np.ndarray, int]:
    """Normalise to sum 1 then water-fill so no pollster's total exceeds `cap` (`cap_few` if < 4 distinct
    pollsters). Excess goes pro rata to the polls of uncapped pollsters. Returns (weights, iterations)."""
    w = np.asarray(w, dtype=float)
    if w.sum() <= 0:
        return w, 0
    w = w / w.sum()
    pollster = np.asarray(pollster, dtype=object)
    names = pd.unique(pollster)
    c = cap if len(names) >= 4 else cap_few
    if len(names) * c < 1.0 - 1e-12:  # cap cannot be met (e.g. a single pollster): leave as normalised
        return w, 0
    capped: set = set()
    for it in range(1, max_iter + 1):
        totals = {p: w[pollster == p].sum() for p in names}
        over = [p for p in names if p not in capped and totals[p] > c + 1e-12]
        if not over:
            return w, it - 1
        capped |= set(over)
        for p in over:
            m = pollster == p
            w[m] *= c / totals[p]
        free = np.array([p not in capped for p in pollster])
        excess = 1.0 - w.sum()
        if free.any() and w[free].sum() > 0:
            w[free] *= 1.0 + excess / w[free].sum()
    return w, max_iter
