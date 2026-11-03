"""County swing construction and exact calibration (plan §6.8, §11.1)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from senate.county.backtest import backtest_states, summarize
from senate.county.calibrate import calibrate
from senate.county.construct import build_state, county_raw_swing, omega_groups, regional_weights

RNG = np.random.default_rng(7)


def test_calibration_exact_no_clip():
    m0 = RNG.uniform(-30, 30, 50)
    s_raw = RNG.normal(8, 3, 50)
    w = RNG.uniform(1e3, 1e5, 50)
    s, lam = calibrate(m0, s_raw, w, 9.73)
    nu = w / w.sum()
    assert abs((nu * s).sum() - 9.73) < 1e-9
    assert lam == pytest.approx(9.73 - (nu * s_raw).sum(), abs=1e-8)  # closed form without clipping


def test_calibration_exact_with_clip():
    m0 = np.array([95.0, 90.0, -95.0, 5.0, -10.0, 60.0])
    s_raw = np.array([8.0, 9.0, 4.0, 12.0, 6.0, 7.0])
    w = np.array([1e4, 2e4, 1e4, 5e4, 4e4, 3e4])
    s, lam = calibrate(m0, s_raw, w, 7.0)
    nu = w / w.sum()
    assert abs((nu * s).sum() - 7.0) < 1e-6
    assert np.all(m0 + s <= 100 + 1e-9) and np.all(m0 + s >= -100 - 1e-9)
    assert (m0 + s)[0] == pytest.approx(100.0)  # the near-100 county clipped


@settings(max_examples=200, deadline=None)
@given(st.integers(2, 40), st.integers(0, 2**32 - 1), st.floats(-15, 15))
def test_calibration_property(n, seed, S):
    r = np.random.default_rng(seed)
    m0 = r.uniform(-90, 90, n)
    s_raw = r.normal(0, 8, n)
    w = r.uniform(0, 1e5, n) + 1.0
    nu = w / w.sum()
    if not -100 <= (nu * m0).sum() + S <= 100:
        return
    s, _ = calibrate(m0, s_raw, w, S)
    assert abs((nu * s).sum() - S) < 1e-6


def test_calibration_flat_weights_equals_mean_shift():
    m0 = RNG.uniform(-20, 20, 30)
    s_raw = RNG.normal(5, 2, 30)
    s, lam = calibrate(m0, s_raw, np.ones(30), 6.0)
    assert np.allclose(s, s_raw + (6.0 - s_raw.mean()))
    assert lam == pytest.approx(6.0 - s_raw.mean())


def _toy():
    groups = ["wnh_college", "wnh_noncollege", "black", "hispanic", "asian", "other"]
    ids = [f"13{i:03d}" for i in range(8)]
    omega = pd.DataFrame(RNG.uniform(100, 5000, (8, 6)), index=ids, columns=groups)
    region = pd.Series(["south"] * 4 + ["black_belt"] * 4, index=ids)
    delta = pd.DataFrame([[6, 14, 7, 11, 8, 10], [5, 12, 9, 10, 7, 9]], index=["south", "black_belt"], columns=groups,
                         dtype=float)
    return groups, ids, omega, region, delta


def test_tilt_is_mean_zero_at_regional_weights():
    groups, ids, omega, region, delta = _toy()
    reg_w = regional_weights(omega, region)
    raw = county_raw_swing(9.73, omega, region, delta, reg_w)
    for r in ("south", "black_belt"):
        sel = region == r
        tot = omega[sel].sum(axis=1)
        # omega-weighted mean tilt within a region is zero by construction
        assert (raw.tilt[sel] * tot).sum() / tot.sum() == pytest.approx(0.0, abs=1e-9)


def test_tilt_cap():
    groups, ids, omega, region, delta = _toy()
    delta = delta * 10
    raw = county_raw_swing(9.0, omega, region, delta, regional_weights(omega, region), max_tilt=6.0)
    assert raw.tilt.abs().max() <= 6.0 + 1e-12


def test_build_state_methods_and_constraint():
    groups, ids, omega, region, delta = _toy()
    counties = pd.DataFrame({"m0": RNG.uniform(-30, 30, 8), "region": region})
    reg_w = regional_weights(omega, region)
    ok = build_state("GA", 9.73, counties, omega, delta, reg_w, "ok")
    assert (ok.county_method == "ei_crosstab").all()
    fb = build_state("GA", 9.73, counties, omega, delta, reg_w, "fallback")
    assert (fb.county_method == "uniform").all()
    z = pd.Series(RNG.normal(size=8), index=ids)
    ao = build_state("GA", 9.73, counties, omega, delta, reg_w, "fallback", z, 0.5)
    assert (ao.county_method == "age_only").all()
    for r in (ok, fb, ao):
        nu = r.omega / r.omega.sum()
        assert abs((nu * r.s).sum() - 9.73) < 1e-6
    assert np.allclose(fb.s, 9.73)  # uniform: every county moves by S_s


def test_omega_groups_keeps_state_total():
    rows = []
    for st_, ids in (("GA", ["13001", "13002"]), ("AL", ["01001"])):
        for gid in ids:
            for g, n in zip(["wnh_college", "black"], [1000.0, 800.0], strict=True):
                rows.append({"geoid": gid, "state_po": st_, "group": g, "n_group": n})
    df = pd.DataFrame(rows)
    om = omega_groups(df, {"wnh_college": 0.85, "black": 0.66}, ["wnh_college", "black"])
    for st_ in ("GA", "AL"):
        ids = df[df.state_po == st_].geoid.unique()
        assert om.loc[ids].to_numpy().sum() == pytest.approx(df[df.state_po == st_].n_group.sum())
    # drop-off shifts the mix toward the group that drops off less
    assert (om["wnh_college"] / om["black"]).iloc[0] > 1000 / 800


def test_backtest_pattern_beats_uniform_when_pattern_is_real():
    groups, ids, omega, region, delta = _toy()
    m0 = pd.Series(RNG.uniform(-30, 30, 8), index=ids)
    state_of = pd.Series("GA", index=ids)
    w = omega.sum(axis=1)
    reg_w = regional_weights(omega, region)
    truth = county_raw_swing(9.0, omega, region, delta, reg_w).s_raw  # true shifts follow the group pattern
    m1 = m0 + truth
    bt = backtest_states(m0, m1, w, state_of, omega, region, delta, 1.0)
    res = summarize(bt)
    assert res["rmse_model_weighted"] < res["rmse_uniform_weighted"]
