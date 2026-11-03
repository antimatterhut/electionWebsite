"""House effects by alternating weighted least squares (plan §6.2 Step 3)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import HouseEffect

ITERATIONS = 5


def _wmean(x: np.ndarray, w: np.ndarray) -> float:
    return float(np.average(x, weights=w)) if w.sum() > 0 else 0.0


def estimate_house_effects(polls: pd.DataFrame, cfg: HouseEffect, min_polls: int | None = None) -> dict[str, float]:
    """polls: contest, pollster, margin, w (raw weight). Pools the generic ballot and every Senate contest; contest
    means are fixed effects so national/state level differences do not leak into h. Pollsters with fewer than
    `min_polls` polls (default cfg.min_polls) are held at 0. Returns {pollster: h}, clipped to +-max_abs."""
    min_polls = cfg.min_polls if min_polls is None else min_polls
    d = polls[["contest", "pollster", "margin", "w"]].dropna().reset_index(drop=True)
    d = d[d.w > 0].reset_index(drop=True)
    if d.empty:
        return {}
    counts = d.groupby("pollster").size()
    pollsters = list(counts.index)
    h = dict.fromkeys(pollsters, 0.0)
    eligible = {p for p in pollsters if counts[p] >= min_polls}
    vol = counts.astype(float)
    n_eff = d.groupby("pollster").w.apply(lambda w: w.sum() ** 2 / (w**2).sum())
    for _ in range(ITERATIONS):
        d["h"] = d.pollster.map(h)
        theta = d.assign(adj=d.margin - d.h).groupby("contest").apply(
            lambda g: _wmean(g.adj.to_numpy(), g.w.to_numpy()), include_groups=False)
        d["theta"] = d.contest.map(theta)
        for p in eligible:
            g = d[d.pollster == p]
            r_p = _wmean((g.margin - g.theta).to_numpy(), g.w.to_numpy())
            h[p] = n_eff[p] / (n_eff[p] + cfg.shrink_k) * r_p
        if eligible:
            ev = np.array([h[p] for p in eligible])
            c = _wmean(ev, np.array([vol[p] for p in eligible]))
            for p in eligible:
                h[p] -= c
    for p in eligible:
        h[p] = float(np.clip(h[p], -cfg.max_abs, cfg.max_abs))
    return h
