"""County swing construction and exact calibration (plan §6.8, §11.1)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from senate.county.backtest import backtest_states, summarize
from senate.county.calibrate import calibrate
from senate.county.construct import build_state, county_raw_swing, omega_groups

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


def test_tilt_is_mean_zero_at_state_weights():
    groups, ids, omega, region, delta = _toy()
    raw = county_raw_swing(9.73, omega, region, delta)
    tot = omega.sum(axis=1)
    assert (raw.tilt * tot).sum() / tot.sum() == pytest.approx(0.0, abs=1e-9)


def test_tilt_keeps_between_region_difference():
    groups = ["a", "b"]
    ids = ["r0", "r1", "s0", "s1"]
    omega = pd.DataFrame([[900, 100], [800, 200], [100, 900], [200, 800]], index=ids, columns=groups, dtype=float)
    region = pd.Series(["A", "A", "B", "B"], index=ids)
    delta = pd.DataFrame([[20.0, 0.0], [10.0, 0.0]], index=["A", "B"], columns=groups)  # A moves more for group a
    raw = county_raw_swing(5.0, omega, region, delta)
    assert raw.tilt[["r0", "r1"]].mean() > raw.tilt[["s0", "s1"]].mean()
    assert raw.tilt[["r0", "r1"]].mean() > 0 > raw.tilt[["s0", "s1"]].mean()
    assert county_raw_swing(5.0, omega, region, delta, max_tilt=None).tilt.abs().max() > 0


def test_tilt_cap():
    groups, ids, omega, region, delta = _toy()
    delta = delta * 10
    raw = county_raw_swing(9.0, omega, region, delta, max_tilt=6.0)
    assert raw.tilt.abs().max() <= 6.0 + 1e-12
    z = pd.Series(RNG.normal(size=8) * 50, index=omega.index)
    tot = county_raw_swing(9.0, omega, region, delta, z_age=z, beta_age=1.0,
                           max_tilt=6.0, urban_term=z)
    assert (tot.s_raw - 9.0).abs().max() <= 6.0 + 1e-12  # the cap applies to the total tilt


def test_overlap_shrink_scales_age_and_urban_terms():
    groups, ids, omega, region, delta = _toy()
    z = pd.Series(RNG.normal(size=8), index=ids)
    kw = dict(z_age=z, beta_age=1.0, urban_term=z * 2, max_tilt=50.0)
    full = county_raw_swing(9.0, omega, region, delta, **kw)
    half = county_raw_swing(9.0, omega, region, delta, overlap_shrink=(0.5, 0.25), **kw)
    assert np.allclose(half.age_term, 0.5 * full.age_term) and np.allclose(half.urban_term, 0.25 * full.urban_term)
    assert np.allclose(half.tilt, full.tilt)


def test_build_state_methods_and_constraint():
    groups, ids, omega, region, delta = _toy()
    counties = pd.DataFrame({"m0": RNG.uniform(-30, 30, 8), "region": region})
    ok = build_state("GA", 9.73, counties, omega, delta, "ok")
    assert (ok.county_method == "group_tilt").all()
    # EI status no longer gates the tilt: a priors-only fallback still gets the group tilt
    fb = build_state("GA", 9.73, counties, omega, delta, "fallback")
    assert (fb.county_method == "group_tilt").all() and fb.tilt.abs().max() > 0
    un = build_state("GA", 9.73, counties, omega, None, "fallback")
    assert (un.county_method == "uniform").all()
    z = pd.Series(RNG.normal(size=8), index=ids)
    ao = build_state("GA", 9.73, counties, omega, None, "fallback", z, 0.5)
    assert (ao.county_method == "age_only").all()
    ga = build_state("GA", 9.73, counties, omega, delta, "fallback", z, 0.5)
    assert (ga.county_method == "group_tilt+age").all()
    gu = build_state("GA", 9.73, counties, omega, delta, "ok", z, 0.5, urban_term=z)
    assert (gu.county_method == "group_tilt+age+urban").all()
    for r in (ok, fb, un, ao, ga, gu):
        nu = r.omega / r.omega.sum()
        assert abs((nu * r.s).sum() - 9.73) < 1e-6
    assert np.allclose(un.s, 9.73)  # uniform: every county moves by S_s


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
    truth = county_raw_swing(9.0, omega, region, delta).s_raw  # true shifts follow the group pattern
    m1 = m0 + truth
    bt = backtest_states(m0, m1, w, state_of, omega, region, delta, 1.0)
    res = summarize(bt)
    assert res["rmse_model_weighted"] < res["rmse_uniform_weighted"]


# --- urban / area term (MODEL_FIXES Task 4) ---
def test_urban_terms_mean_zero_and_ordered():
    from senate.county.urban import urban_terms

    cls = pd.Series(["urban", "urban", "suburban", "rural"], index=list("abcd"))
    nu = pd.Series([4.0, 2.0, 3.0, 1.0], index=cls.index)
    t = urban_terms(cls, nu, {"urban": 2.0, "suburban": 0.0, "rural": -4.0})
    assert (t * nu).sum() / nu.sum() == pytest.approx(0.0, abs=1e-12)
    assert t["a"] > t["c"] > t["d"]
    assert (urban_terms(cls, nu, {}) == 0).all()


def test_classify_terciles_and_nchs():
    from senate.county.urban import classify

    ids = pd.Index([f"{i:05d}" for i in range(9)])
    cv = pd.Series(range(1, 10), index=ids, dtype=float)
    lab, m = classify(ids, cv)
    assert m == "cvap_terciles" and lab.iloc[0] == "rural" and lab.iloc[-1] == "urban" and (lab == "suburban").sum() == 3
    nchs = pd.DataFrame({"fips": ids, "code": [1, 2, 3, 4, 5, 6, 1, 2, 6]})
    lab, m = classify(ids, cv, nchs)
    assert m == "nchs2023" and list(lab[:3]) == ["urban", "suburban", "suburban"] and lab.iloc[5] == "rural"


def test_class_swings_shrink_toward_pooled():
    from senate.county.urban import class_swings

    cells = pd.DataFrame({"group": ["urban", "rural"], "z": [10.0, 2.0], "var": [1.0, 1.0], "n_group": [500, 500]})
    s = class_swings(cells)
    assert s["urban"]["delta"] > s["rural"]["delta"] and 2.0 < s["rural"]["delta"] < 10.0


def test_true_group_swings_from_validated_rows():
    from senate.county.backtest import true_group_swings

    v = pd.DataFrame({"geography": "national", "group_value": ["black", "black", "hispanic", "hispanic", "asian"],
                      "year": [2020, 2024, 2020, 2024, 2024], "d_share_2p": [0.90, 0.85, 0.60, 0.52, 0.6]})
    s = true_group_swings(v)
    assert s == {"black": pytest.approx(-10.0), "hispanic": pytest.approx(-16.0)}  # asian: no 2020 row


def test_ei_elasticity_scales_lopsided_groups_down():
    from senate.county.construct import ei_elasticity
    idx = pd.Index(["a", "b", "c"])
    omega = pd.DataFrame({"g": [1.0, 1.0, 1.0]}, index=idx)
    theta = pd.DataFrame({"g": [0.5, 0.9, np.nan]}, index=idx)
    st = pd.Series("TX", index=idx)
    e = ei_elasticity(theta, omega, st, 1.0)
    assert e.loc["a", "g"] > e.loc["b", "g"] and e.loc["c", "g"] == 1.0
    assert (ei_elasticity(theta, omega, st, 0.0) == 1.0).all().all()
