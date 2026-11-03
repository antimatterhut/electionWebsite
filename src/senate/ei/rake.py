"""Rake EI group baselines to the validated-voter group contrasts (the EI group levels are weakly identified).

EI only sees one vote total per county, so the white education split and the smaller groups are pinned down mostly
by its priors and random effects; state fits drift ~13 pts RMS from the validated-voter 2024 group margins. This
step shifts each group's logit theta by a common offset o_g so the group's pooled baseline hits

    target_g = invlogit(logit(validated_g) + delta),

then re-applies each county's accounting shift c_i (sum_g n_ig theta_ig = D votes), alternating to convergence.
delta absorbs the fact that the modelled states are not the nation (the validated shares are national), so the
validated numbers fix the *contrasts between groups*, and the actual vote fixes the level. Groups with no validated
baseline ('other') are not targeted; they take whatever the county identity leaves.
"""
from __future__ import annotations

import numpy as np

from .model_rxc import logit
from .run_state import reconcile


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def solve_delta(share: np.ndarray, target: np.ndarray, free_theta: np.ndarray, d_total: float) -> float:
    """delta s.t. sum_g share_g sigmoid(logit target_g + delta) over targeted g + untargeted free_theta = d_total.

    share: pooled group shares (sum 1); target: validated D share per group, NaN where none; free_theta: pooled theta
    used for NaN groups."""
    ok = ~np.isnan(target)
    lo, hi = -4.0, 4.0
    for _ in range(80):
        mid = (lo + hi) / 2
        tot = (share[ok] * _sig(logit(target[ok]) + mid)).sum() + (share[~ok] * free_theta[~ok]).sum()
        lo, hi = (mid, hi) if tot < d_total else (lo, mid)
    return (lo + hi) / 2


def rake(L: np.ndarray, n: np.ndarray, vd: np.ndarray, target: np.ndarray, iters: int = 300, tol: float = 1e-9
         ) -> tuple[np.ndarray, np.ndarray, float]:
    """Group offsets o (G,), county shifts c (I,), delta; final logit = L + o + c[:, None].

    L: (I, G) logit theta; n: (I, G) group voters; vd: (I,) D votes; target: (G,) validated D share (NaN = free)."""
    wg = n.sum(0)
    share = wg / wg.sum()
    th0 = _sig(L + reconcile(_sig(L), n, vd)[:, None])
    free = (th0 * n).sum(0) / wg
    ok = ~np.isnan(target)
    if not ok.any():
        return np.zeros(L.shape[1]), reconcile(_sig(L), n, vd), 0.0
    delta = solve_delta(share, target, free, float(vd.sum() / n.sum()))
    tgt = np.where(ok, _sig(logit(np.where(ok, target, 0.5)) + delta), np.nan)
    off = np.zeros(L.shape[1])
    for _ in range(iters):
        c = reconcile(_sig(L + off), n, vd)
        Lc = L + off + c[:, None]
        step = np.zeros_like(off)
        for j in np.flatnonzero(ok):
            lo, hi = -3.0, 3.0
            for _ in range(50):
                m = (lo + hi) / 2
                p = (n[:, j] * _sig(Lc[:, j] + m)).sum() / wg[j]
                lo, hi = (m, hi) if p < tgt[j] else (lo, m)
            step[j] = (lo + hi) / 2
        off += step
        if np.abs(step).max() < tol:
            break
    return off, reconcile(_sig(L + off), n, vd), float(delta)
