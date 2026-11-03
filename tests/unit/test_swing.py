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


def test_default_weights_are_2_to_1(cfg):
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
