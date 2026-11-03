"""LV/RV/A population adjustment (plan §6.2 Step 4)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import LvRv

SHRINK_K = 5.0
A_FACTOR = 1.5


def estimate_delta_lv(polls: pd.DataFrame, cfg: LvRv, keys: tuple[str, ...] = ("contest", "pollster", "field_end")
                      ) -> tuple[float, int]:
    """delta_LV = mean(m_LV - m_RV) over pollster-period pairs reporting both, shrunk toward the prior with k=5.
    Returns (delta, n_pairs); the prior is used until >= min_pairs pairs exist."""
    keys = [k for k in keys if k in polls.columns]
    lv = polls[polls["pop"] == "LV"].groupby(keys).margin.mean()
    rv = polls[polls["pop"] == "RV"].groupby(keys).margin.mean()
    diff = (lv - rv).dropna()
    n = len(diff)
    if n < cfg.min_pairs:
        return cfg.prior_delta, n
    raw = float(diff.mean())
    return (n * raw + SHRINK_K * cfg.prior_delta) / (n + SHRINK_K), n


def adjust_population(polls: pd.DataFrame, delta_lv: float) -> pd.DataFrame:
    """Shift RV polls by +delta_LV and A polls by 1.5 delta_LV so they read like LV polls; column `delta`."""
    out = polls.copy()
    out["delta"] = np.where(out["pop"] == "RV", delta_lv, np.where(out["pop"] == "A", A_FACTOR * delta_lv, 0.0))
    return out
