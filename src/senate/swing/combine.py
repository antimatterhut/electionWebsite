"""State swing = national prior updated by the state's polls (precision weighting, MODEL_FIXES Task 1), the legacy
fixed national:poll weights (plan §6.5), and the optional market blend (§6.5.1)."""
from __future__ import annotations

import math

from ..config import SwingPrecision


def state_swing(s_nat, s_poll, a=2.0, b=1.0, polled=True, scale_by_volume=False, n_eff=None, n_ref=6.0):
    """Fixed mode: S_base = (a S_nat + b S_poll) / (a + b); unpolled states take S_nat ('national_fallback')."""
    if not polled:
        return s_nat, "national_fallback"
    b_eff = b * (min(1.0, n_eff / n_ref) if scale_by_volume else 1.0)
    return (a * s_nat + b_eff * s_poll) / (a + b_eff), "combined"


def poll_variance(n_eff: float, sigma_poll: float, sigma_bias: float) -> float:
    """Variance of the state poll average as a measurement of the race: sampling (shrinks with n_eff) plus the
    irreducible state-polling error sigma_bias (does not)."""
    return sigma_poll**2 / max(n_eff, 1e-9) + sigma_bias**2


def precision_swing(s_prior: float, s_poll: float, n_eff: float, sigma_poll: float, p: SwingPrecision,
                    polled: bool = True, s_fallback: float | None = None) -> tuple[float, str, float, float, float]:
    """Normal-normal update. Returns (swing, source, w_poll, poll_var, posterior_sd).

    The prior (national swing + optional incumbency) has variance sigma_prior^2: candidate effects and state-specific
    deviation from the national environment. w_poll = prior_var / (prior_var + poll_var), clipped to [w_min, w_max].
    Unpolled states get s_fallback (the plain national swing, no incumbency shift; default s_prior), w_poll 0, source
    'national_fallback'."""
    if not polled:
        return (s_prior if s_fallback is None else s_fallback), "national_fallback", 0.0, math.nan, p.sigma_prior
    pv = poll_variance(n_eff, sigma_poll, p.sigma_bias)
    w = min(p.w_max, max(p.w_min, p.sigma_prior**2 / (p.sigma_prior**2 + pv)))
    post_sd = math.sqrt(1.0 / (1.0 / p.sigma_prior**2 + 1.0 / pv))
    return w * s_poll + (1 - w) * s_prior, "combined", w, pv, post_sd


def state_swing_with_market(s_base, s_mkt, v24h, mu_max=0.10, v_ref=50_000, scale=True, cap=0.20):
    """Small market blend on top of S_base; mu = 0 when there is no qualifying market. Not wired into the Phase 2
    pipeline (no market ingest yet), so every run reports market_weight 0."""
    if s_mkt is None:
        return s_base, 0.0
    mu = min(cap, mu_max * (min(1.0, v24h / v_ref) if scale else 1.0))
    return (1 - mu) * s_base + mu * s_mkt, mu
