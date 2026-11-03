"""Group construction, EI helpers, crosstab harmonisation and shrinkage (plan §6.6-6.7, §11.1)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from senate.crosstab.harmonize import NONWHITE, age_gradient, baseline_table, harmonize
from senate.crosstab.hier_model import analytic_posterior, prior_only
from senate.config import load_config
from senate.ei import inputs as I
from senate.ei.groups import GROUPS, assign_regions, build_county_groups
from senate.ei.model_rxc import logit
from senate.ei.run_state import make_jobs, prior_only as ei_prior_only, reconcile
from senate.ei.shift_ei import group_pattern
from senate.ei.validation import compare

KAPPA = {"wnh_college": 1.00, "wnh_noncollege": 0.88, "black": 0.86, "hispanic": 0.72, "asian": 0.75, "other": 0.75}


def _cvap(geoids):
    rows = []
    for g in geoids:
        for race, n in zip(["wnh", "black", "hisp", "asian", "other"], [5000, 3000, 1500, 400, 100], strict=True):
            rows.append({"geoid": g, "race5": race, "cvap": n, "moe": 10.0})
    return pd.DataFrame(rows)


def test_group_voters_sum_to_county_votes():
    votes = pd.DataFrame({"geoid": ["13001", "13002"], "state_po": "GA", "votes_d": [4000, 100], "votes_r": [3000, 900]})
    edu = pd.DataFrame({"geoid": ["13001"], "college_share_wnh": [0.5]})
    t = build_county_groups(votes, _cvap(votes.geoid), edu, KAPPA)
    assert t.groupby("geoid").n_group.sum().to_numpy() == pytest.approx([7000, 1000])
    assert t.groupby("geoid").pi.sum().to_numpy() == pytest.approx([1, 1])
    wnh = t[t.group.str.startswith("wnh")].groupby("geoid").cvap_g.sum()
    assert wnh.to_numpy() == pytest.approx([5000, 5000])
    assert set(t.loc[t.geoid == "13002", "edu_source"]) == {"default"}  # no edu row -> flagged default


def test_regions_blackbelt_and_riogrande():
    sp = pd.Series(["GA", "GA", "TX", "TX", "OH"])
    cv = pd.DataFrame({"wnh": [50, 100, 20, 80, 100], "black": [50, 0, 0, 0, 0], "hisp": [0, 0, 80, 20, 0],
                       "asian": 0, "other": 0})
    assert assign_regions(sp, cv).tolist() == ["black_belt", "south", "rio_grande", "south", "midwest"]


def test_small_states_pooled_by_division():
    jobs = make_jobs({"GA": 159, "NH": 10, "MA": 14, "DE": 3, "TX": 254}, 25)
    names = {j.name: j.states for j in jobs}
    assert names["GA"] == ["GA"] and names["TX"] == ["TX"]
    assert names["div_new_england"] == ["MA", "NH"]
    assert names["div_south_atlantic"] == ["DE"]


def test_reconcile_reproduces_county_votes():
    r = np.random.default_rng(1)
    n = r.uniform(100, 9000, (20, 6))
    theta = r.uniform(0.2, 0.8, (20, 6))
    vd = (n * np.clip(theta + 0.05, 0, 1)).sum(axis=1)
    c = reconcile(theta, n, vd)
    pred = (n / (1 + np.exp(-(logit(theta) + c[:, None])))).sum(axis=1)
    assert np.abs(pred / vd - 1).max() < 1e-6


def test_prior_only_fallback_is_wide():
    from senate.ei.model_rxc import EIData

    d = EIData(np.array(["a", "b"]), np.array(["X", "X"]), np.array([5.0, 5.0]), np.array([10.0, 10.0]),
               np.ones((2, 6)), np.zeros((2, 0)), np.zeros(2, int), ["south"], np.full(6, 0.5), np.full(6, 0.35), GROUPS)
    t = ei_prior_only(d)
    assert (t.theta_p90 - t.theta_p10).min() > 0.1


def test_priors_use_placeholders_then_studies():
    p = I.group_priors(None, GROUPS)
    assert set(p.prior_level) == {"placeholder"}
    v = pd.DataFrame({"study": ["pew", "ap"], "year": 2024, "geography": "national", "group_value": "black",
                      "d_share_2p": [0.84, 0.90]})
    q = I.group_priors(v, GROUPS).set_index("group")
    assert q.loc["black", "mu"] == pytest.approx(0.87) and q.loc["black", "prior_level"] == "national"
    assert q.loc["black", "sd"] >= 0.20
    assert q.loc["hispanic", "prior_level"] == "placeholder"


def test_persisted_pattern_is_deviation_from_regional_average():
    shift = pd.DataFrame({"region": ["south"] * 3, "group": GROUPS[:3], "delta_mean": [2.0, 6.0, 1.0]})
    w = pd.DataFrame([[0.5, 0.3, 0.2]], index=["south"], columns=GROUPS[:3])
    p = group_pattern(shift, w)
    assert (w * p).sum(axis=1).iloc[0] == pytest.approx(0.0)
    assert p.loc["south", GROUPS[1]] > 0 > p.loc["south", GROUPS[0]]


def _ei_for_baselines():
    rows = []
    for g, th in zip(GROUPS, [0.55, 0.35, 0.85, 0.45, 0.60, 0.50], strict=True):
        rows.append({"geoid": "13001", "group": g, "theta_mean": th, "theta_p10": th - 0.03, "theta_p90": th + 0.03,
                     "n_group": 1000.0})
    geo = pd.DataFrame({"geoid": ["13001"], "state_po": ["GA"], "region": ["south"]})
    return pd.DataFrame(rows), geo


def _crosstab_rows(group_value, n=400, d=60, r=40, geography="national"):
    return {"poll_id": "p1", "geography": geography, "group_dim": "race", "group_value": group_value, "n_group": n,
            "dside_pct": d, "rside_pct": r}


def test_group_harmonization_nonwhite_split():
    ei, geo = _ei_for_baselines()
    base = {lvl: baseline_table(ei, geo, lvl) for lvl in ("national", "region", "state")}
    gw = pd.DataFrame({"geography": "national", "group": GROUPS, "w": 1000.0})
    cx = pd.DataFrame([_crosstab_rows("nonwhite"), _crosstab_rows("black")])
    cells, _ = harmonize(cx, base, gw, deff=1.5)
    nw = cells[cells.nonwhite]
    assert sorted(nw.group) == sorted(NONWHITE) and len(nw) == 4
    assert nw.n_group.sum() == pytest.approx(400)  # n split by group size
    direct = cells[cells.group == "black"].iloc[0]
    p = 0.6
    samp = (100 * 2 * np.sqrt(p * (1 - p)) / np.sqrt(400 / 1.5)) ** 2
    sd_b = direct["var"] - samp  # baseline variance part
    assert sd_b >= 0
    # nonwhite variance = 2 x (sampling + baseline sd of the combined baseline)
    assert (nw["var"] > 2 * samp).all() and (nw["var"] < 2 * samp + 2 * 50).all()


def test_small_cells_dropped_and_age_split():
    ei, geo = _ei_for_baselines()
    base = {lvl: baseline_table(ei, geo, lvl) for lvl in ("national", "region", "state")}
    gw = pd.DataFrame({"geography": "national", "group": GROUPS, "w": 1000.0})
    age = {**_crosstab_rows("18-29"), "group_dim": "age"}
    cells, age_cells = harmonize(pd.DataFrame([_crosstab_rows("black", n=50), age]), base, gw, 1.5, min_n=75)
    assert cells.empty and len(age_cells) == 1


def test_group_shrinkage_toward_overall():
    """Tiny n (huge variance) => delta_g ~ S_ref + prior pattern; large n => the poll's own value."""
    s_ref, lam_p = 9.0, 0.5 * 2.0
    m_tiny, _ = analytic_posterior(np.array([20.0]), np.array([1e8]), lam_p, 9.0, s_ref)
    assert m_tiny == pytest.approx(s_ref + lam_p, abs=1e-3)
    m_big, v_big = analytic_posterior(np.array([14.0] * 20), np.array([1.0] * 20), lam_p, 9.0, s_ref)
    assert m_big == pytest.approx(s_ref + 14.0, abs=0.1)
    assert v_big < 0.06


def test_group_swing_prior_only_fallback():
    cfg = load_config()
    out = prior_only(GROUPS, ["south", "midwest"], pd.Series({"black": 2.0}), 9.0, cfg.ei.pattern_persistence)
    assert (out[out.group == "black"].delta_mean == 9.0 + 0.5 * 2.0).all()
    assert (out.n_polls == 0).all() and (out.shrinkage_factor == 1.0).all()


def test_age_gradient_needs_baseline():
    a = pd.DataFrame([{**_crosstab_rows("18-29"), "group_dim": "age"}, {**_crosstab_rows("65+", d=45, r=55),
                                                                         "group_dim": "age"}])
    assert age_gradient(a, None)["age_gradient_per_sd"] == 0.0
    base = pd.DataFrame({"group_value": ["18-29", "65+"], "d_share_2p": [0.55, 0.45]})
    g = age_gradient(a, base, sd_young_share=0.05)
    assert g["reason"] == "ok" and g["age_gradient_per_sd"] != 0.0


def test_ei_flags_threshold_and_hard_fail():
    cfg = load_config()
    ei, geo = _ei_for_baselines()
    v = pd.DataFrame({"study": ["pew", "pew"], "year": 2024, "geography": "national",
                      "group_value": ["black", "hispanic"], "d_share_2p": [0.85 - 0.09, 0.45 - 0.13]})
    tbl, fails = compare(ei, geo, v, cfg)
    t = tbl.set_index("group")
    assert bool(t.loc["black", "flag"]) and bool(t.loc["hispanic", "flag"])
    assert abs(t.loc["black", "diff"] - 9.0) < 1e-6
    assert fails == ["hispanic@national"]  # 13 > 12 and group >= 10% of voters
    empty, none = compare(ei, geo, None, cfg)
    assert empty.empty and none == []
