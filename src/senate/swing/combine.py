"""The 2:1 national/state-poll combination (plan §6.5) and the optional market blend (§6.5.1)."""
from __future__ import annotations


def state_swing(s_nat, s_poll, a=2.0, b=1.0, polled=True, scale_by_volume=False, n_eff=None, n_ref=6.0):
    """S_base = (a S_nat + b S_poll) / (a + b); unpolled states take S_nat ('national_fallback')."""
    if not polled:
        return s_nat, "national_fallback"
    b_eff = b * (min(1.0, n_eff / n_ref) if scale_by_volume else 1.0)
    return (a * s_nat + b_eff * s_poll) / (a + b_eff), "combined"


def state_swing_with_market(s_base, s_mkt, v24h, mu_max=0.10, v_ref=50_000, scale=True, cap=0.20):
    """Small market blend on top of S_base; mu = 0 when there is no qualifying market. Not wired into the Phase 2
    pipeline (no market ingest yet), so every run reports market_weight 0."""
    if s_mkt is None:
        return s_base, 0.0
    mu = min(cap, mu_max * (min(1.0, v24h / v_ref) if scale else 1.0))
    return (1 - mu) * s_base + mu * s_mkt, mu
