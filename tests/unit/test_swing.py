"""Swing math and baselines (plan §11.1)."""
from __future__ import annotations

import pandas as pd
import pytest

from senate.polls.average import PollAverage
from senate.swing import baseline as base
from senate.swing.combine import state_swing, state_swing_with_market
from senate.swing.national import national_swing
from senate.swing.state import is_polled, state_poll_swing


def test_margin_2p_basic():
    assert base.baseline_margin(60, 40) == pytest.approx(20.0)
    with pytest.raises(ValueError):
        base.baseline_margin(0, 0)


def test_baseline_ga_worked_example():
    assert base.baseline_margin(2_548_017, 2_663_117) == pytest.approx(-2.21, abs=0.01)


def test_margin_state_from_county_sums():
    votes = pd.DataFrame({"state_po": ["XX", "XX"], "votes_d": [900, 100], "votes_r": [100, 400]})
    s = base.state_baselines(votes).iloc[0]
    county_mean = (base.baseline_margin(900, 100) + base.baseline_margin(100, 400)) / 2
    assert s.m0 == pytest.approx(base.baseline_margin(1000, 500))
    assert s.m0 != pytest.approx(county_mean)


def test_national_swing_sign():
    assert national_swing(9.0, -1.5) == pytest.approx(10.5)
    assert national_swing(9.0, 4.5) == pytest.approx(4.5)


def test_state_poll_swing():
    assert state_poll_swing(6.0, -2.2) == pytest.approx(8.2)


def test_state_swing_2to1():
    s, src = state_swing(10.5, 8.2)
    assert s == pytest.approx(9.7333, abs=1e-4) and src == "combined"


def test_state_swing_unpolled_fallback():
    assert state_swing(10.5, float("nan"), polled=False) == (10.5, "national_fallback")


def test_state_swing_ratio_configurable():
    assert state_swing(10.0, 4.0, a=1, b=1)[0] == pytest.approx(7.0)
    assert state_swing(10.0, 4.0, a=3, b=1)[0] == pytest.approx(8.5)


def test_state_swing_volume_scaled_off_by_default(cfg):
    assert cfg.swing.scale_by_poll_volume is False
    assert state_swing(10.0, 4.0, n_eff=1.0)[0] == pytest.approx(8.0)  # n_eff ignored by default
    assert state_swing(10.0, 4.0, scale_by_volume=True, n_eff=3.0, n_ref=6.0)[0] == pytest.approx((20 + 2) / 2.5)


def test_fixed_weights_still_2_to_1(cfg):
    assert (cfg.swing.weights.national, cfg.swing.weights.state_poll) == (2, 1)


def test_market_weight_zero_without_quotes():
    assert state_swing_with_market(9.0, None, 0.0) == (9.0, 0.0)


def test_market_weight_liquidity_scaling_and_cap():
    thin = state_swing_with_market(9.0, 5.0, 5_000)[1]
    deep = state_swing_with_market(9.0, 5.0, 500_000)[1]
    assert thin < deep <= 0.20


def test_is_polled_rule(cfg):
    ok = PollAverage(5.0, 1.0, 1.5, 2)
    thin = PollAverage(5.0, 1.0, 0.5, 1)
    assert is_polled(ok, cfg.swing.state)
    assert not is_polled(thin, cfg.swing.state)
    assert not is_polled(PollAverage(float("nan"), float("nan"), 0.0, 0), cfg.swing.state)


# --- precision weighting (MODEL_FIXES Task 1) ---
def test_precision_weight_formula_and_clip(cfg):
    from senate.config import SwingPrecision
    from senate.swing.combine import poll_variance, precision_swing

    p = SwingPrecision(sigma_prior=6.0, sigma_bias=2.5, w_min=0.4, w_max=0.9)
    pv = poll_variance(16.0, 3.9, 2.5)
    assert pv == pytest.approx(3.9**2 / 16 + 2.5**2)
    swing, src, w, pv2, sd = precision_swing(12.0, 3.0, 16.0, 3.9, p)
    assert src == "combined" and pv2 == pytest.approx(pv)
    assert w == pytest.approx(36 / (36 + pv))
    assert swing == pytest.approx(w * 3.0 + (1 - w) * 12.0)
    assert sd == pytest.approx((1 / 36 + 1 / pv) ** -0.5)
    # a single noisy poll is floored at w_min (60:40 national:poll); a huge n_eff is capped at w_max
    assert precision_swing(12.0, 3.0, 0.5, 3.9, SwingPrecision(sigma_prior=3.0, sigma_bias=2.5, w_min=0.4, w_max=0.9))[2] == pytest.approx(0.4)
    assert precision_swing(12.0, 3.0, 1e6, 3.9, SwingPrecision(sigma_prior=20, sigma_bias=0.1, w_min=0.4, w_max=0.9))[2] == pytest.approx(0.9)


def test_precision_unpolled_is_prior(cfg):
    from senate.swing.combine import precision_swing

    swing, src, w, pv, sd = precision_swing(11.0, float("nan"), 0.0, 3.9, cfg.swing.precision, polled=False)
    assert (swing, src, w) == (11.0, "national_fallback", 0.0)
    # the incumbency-shifted prior never reaches an unpolled state: it gets the plain national swing
    assert precision_swing(8.0, float("nan"), 0.0, 3.9, cfg.swing.precision, polled=False, s_fallback=11.0)[0] == 11.0


def test_precision_more_polls_more_weight(cfg):
    from senate.swing.combine import precision_swing

    ws = [precision_swing(10.0, 4.0, n, 3.9, cfg.swing.precision)[2] for n in (1, 4, 16, 64)]
    assert ws == sorted(ws)


def test_demographic_deviation_centered_and_signed():
    import numpy as np
    from senate.swing.demographic import state_deviation
    idx = pd.Index(["01001", "01002", "02001"], name="geoid")
    omega = pd.DataFrame({"a": [90.0, 50.0, 10.0], "b": [10.0, 50.0, 90.0]}, index=idx)
    st = pd.Series(["X", "X", "Y"], index=idx)
    reg = pd.Series(["r", "r", "r"], index=idx)
    delta = pd.DataFrame({"a": [5.0], "b": [15.0]}, index=["r"])
    d = state_deviation(omega, st, reg, delta).set_index("state_po")
    # nationally centered: vote-weighted mean of D is zero
    assert abs(np.average(d.D, weights=d.votes)) < 1e-9
    # state Y is mostly group b, which swung more toward D -> positive deviation
    assert d.D["Y"] > 0 > d.D["X"]
    assert d.raw["Y"] == pytest.approx(0.1 * 5 + 0.9 * 15)


def test_demographic_prior_moves_unpolled_state(cfg):
    from datetime import date
    empty = pd.DataFrame(columns=["state_po"])
    gen = pd.DataFrame()
    bl = pd.DataFrame({"state_po": ["NM"], "m0": [6.0]})
    from senate.swing import model as M
    import senate.polls.average as A

    class R:  # minimal stand-in for run_poll_averages: no state polls, generic ballot D+9
        generic = type("G", (), {"margin": 9.0, "n_polls": 1, "n_eff": 1.0, "se": 1.0})()
        states = {}
        delta_lv = 0.0
    orig = M.run_poll_averages
    M.run_poll_averages = lambda *a, **k: R()
    try:
        base_ = M.run_state_model(gen, empty, bl, -2.0, date(2026, 11, 3), cfg, contests={"NM": "NM"})
        demo = M.run_state_model(gen, empty, bl, -2.0, date(2026, 11, 3), cfg, contests={"NM": "NM"},
                                 demo_dev={"NM": 3.0})
    finally:
        M.run_poll_averages = orig
    k = cfg.swing.demographic_prior.kappa
    assert base_["states"].swing[0] == pytest.approx(11.0)
    assert demo["states"].swing[0] == pytest.approx(11.0 + k * 3.0)
    assert demo["states"].s_demo[0] == pytest.approx(k * 3.0)
