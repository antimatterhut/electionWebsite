"""Exact calibration of county swings to the state swing (plan §6.8)."""
from __future__ import annotations

import numpy as np


def calibrate(m0: np.ndarray, s_raw: np.ndarray, w: np.ndarray, S: float) -> tuple[np.ndarray, float]:
    """Find lambda so that the weighted mean of the (clipped) county swings equals S; return (s, lambda).

    Without clipping lambda = S - sum(nu * s_raw). With clipping the left side is monotone non-decreasing in lambda,
    so bisection converges (tol 1e-10, <= 200 iterations).
    """
    m0, s_raw, w = (np.asarray(a, float) for a in (m0, s_raw, w))
    nu = w / w.sum()
    target = (nu * m0).sum() + S
    if not -100.0 <= target <= 100.0:
        raise ValueError(f"calibrate: target statewide margin {target:.3f} outside [-100, 100]")

    def f(lam: float) -> float:
        return (nu * np.clip(m0 + s_raw + lam, -100, 100)).sum() - target

    lo, hi = -200.0, 200.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
        if hi - lo < 1e-10:
            break
    lam = (lo + hi) / 2
    s = np.clip(m0 + s_raw + lam, -100, 100) - m0
    assert abs((nu * s).sum() - S) < 1e-6, "calibration constraint violated"
    return s, lam
