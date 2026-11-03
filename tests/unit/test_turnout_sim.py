"""Phase 5: turnout model, error model, covariance, simulation invariants, outputs, roll-up (plan §6.10-6.12, §11.1)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from senate.backtest import sim_backtest as SB
from senate.ei.groups import GROUPS, REGIONS
from senate.export.to_json import add_simulation
from senate.export.validate_rollup import check_rollup
from senate.sim import covariance as C
from senate.sim import errors as E
from senate.sim import outputs as O
from senate.sim import simulate as S
from senate.sim.run_sim import build_inputs
from senate.turnout import model as T

RNG = np.random.default_rng(11)


# ---------------------------------------------------------------- turnout
def _counties(n=12):
    geoid = [f"{i:05d}" for i in range(n)]
    state_of = pd.Series(["AA"] * (n // 2) + ["BB"] * (n - n // 2), index=geoid)
    share = RNG.dirichlet(np.ones(6), n)
    votes = RNG.uniform(5e3, 5e4, n)
    n_group = pd.DataFrame(share * votes[:, None], index=geoid, columns=GROUPS)
    m0 = pd.Series(RNG.uniform(-40, 40, n), index=geoid)
    return n_group, m0, state_of


def test_group_omega_state_totals_hit_target(cfg):
    n_group, _, state_of = _counties()
    target = pd.Series({"AA": 1.0e5, "BB": 2.0e5})
    om = T.group_omega(n_group, cfg.turnout.dropoff, target, state_of)
    assert om.sum(axis=1).groupby(state_of).sum().to_dict() == pytest.approx(target.to_dict())


def test_turnout_component_zero_when_uniform_dropoff(cfg):
    n_group, m0, state_of = _counties()
    flat = {g: 0.7 for g in GROUPS}
    t = T.state_turnout_totals(n_group.sum(axis=1).groupby(state_of).sum(), pd.Series({"AA": 0.8, "BB": 0.8}), 5.0, 0.0005)
    om = T.group_omega(n_group, flat, t, state_of)
    assert T.turnout_component(n_group, om, m0, state_of).abs().max() < 1e-9


def test_midterm_dropoff_helps_older_whiter_party(cfg):
    """Counties heavy in low-dropoff groups (black/hispanic) are D-leaning: composition effect T_s is negative."""
    n_group, _, state_of = _counties(10)
    dem_heavy = n_group.index[::2]
    n_group.loc[dem_heavy, ["black", "hispanic"]] *= 6
    m0 = pd.Series(np.where(n_group.index.isin(dem_heavy), 30.0, -30.0), index=n_group.index)
    t = n_group.sum(axis=1).groupby(state_of).sum() * 0.8
    om = T.group_omega(n_group, cfg.turnout.dropoff, t, state_of)
    assert (T.turnout_component(n_group, om, m0, state_of) < 0).all()


def test_build_turnout_table_and_identity(cfg):
    n_group, m0, state_of = _counties()
    t = n_group.sum(axis=1).groupby(state_of).sum() * 0.8
    table, comp = T.build_turnout(n_group, m0, state_of, t, cfg)
    assert set(table.columns) == {"geoid", "state_po", "group", "omega_base", "omega_ev", "share_of_state"}
    assert table.groupby("state_po").share_of_state.sum().to_numpy() == pytest.approx(1.0)
    assert table.groupby("state_po").omega_base.sum().to_dict() == pytest.approx(t.to_dict())
    assert (table.omega_ev == table.omega_base).all()  # no early-vote weights supplied
    ev = n_group * RNG.uniform(0.9, 1.1, n_group.shape)
    table2, _ = T.build_turnout(n_group, m0, state_of, t, cfg, ev)
    assert table2.groupby("state_po").omega_ev.sum().to_dict() == pytest.approx(t.to_dict())


def test_rho_state_pooling_and_weights():
    v20 = pd.Series({"A": 100.0, "B": 100.0, "C": 100.0})
    v16 = pd.Series({"A": 100.0, "B": 100.0, "C": 100.0})
    v22 = pd.Series({"A": 80.0, "B": 90.0})
    v18 = pd.Series({"A": 70.0})
    r = T.rho_state(v22, v20, v18, v16, ["A", "B", "C"], {"r22_20": 0.7, "r18_16": 0.3})
    assert r.rho["A"] == pytest.approx(0.7 * 0.8 + 0.3 * 0.7)
    assert r.rho["B"] == pytest.approx(0.7 * 0.9 + 0.3 * 0.7)  # 2018 ratio pooled from A
    assert r.rho["C"] == pytest.approx(0.7 * 0.85 + 0.3 * 0.7)  # both pooled
    assert r.rho_source["A"] == "state" and r.rho_source["C"] == "pooled"


def test_environment_bump():
    v = pd.Series({"A": 1000.0})
    assert T.state_turnout_totals(v, pd.Series({"A": 0.8}), 10.0, 0.0005)["A"] == pytest.approx(1000 * 0.8 * 1.005)


def test_midterm_totals_drops_uncontested():
    t = pd.DataFrame({"state_po": ["A", "B", "C"], "race": ["regular", "regular", "special"],
                      "votes_d": [100, 5, 50], "votes_r": [100, 100, 50]})
    assert T.midterm_totals(t).to_dict() == {"A": 200}


# ---------------------------------------------------------------- error model
def test_defaults_when_no_history(cfg):
    em = E.fit_error_model(pd.DataFrame(columns=["year", "state_po", "race", "poll_avg_margin", "actual_margin",
                                                 "n_polls"]), cfg)
    assert em.source == "config_default" and em.notes
    assert (em.national, em.region, em.state) == (2.5, 2.0, 3.0)


def test_fit_recovers_variance_components(cfg):
    rng = np.random.default_rng(3)
    states = ["PA", "OH", "GA", "NC", "AZ", "NV", "WI", "MI", "TX", "FL", "CO", "NH"]
    rows = []
    for y in (2006, 2010, 2014, 2018, 2022, 2008, 2012, 2016):
        u = rng.normal(0, 3.0)
        v = {r: rng.normal(0, 1.5) for r in set(E.region_of(s) for s in states)}
        for s in states:
            rows.append({"year": y, "state_po": s, "race": "regular", "poll_avg_margin": 0.0, "n_polls": 3,
                         "actual_margin": u + v[E.region_of(s)] + rng.normal(0, 3.0)})
    em = E.fit_error_model(pd.DataFrame(rows), cfg)
    assert em.source == "fitted_reml"
    assert 1.2 < em.national < 6.0 and 1.5 < em.state < 4.5
    assert set(em.comparison) == {"national", "region", "state"}
    leave = E.fit_error_model(pd.DataFrame(rows), cfg, exclude_year=2022)
    assert leave.n_rows == len(rows) - len(states)


def test_county_sd_from_residuals():
    rng = np.random.default_rng(1)
    n = 400
    r = pd.DataFrame({"state_po": np.repeat(["A", "B"], n // 2), "weight": 1e4,
                      "error": rng.normal(0, 2.0, n) + np.repeat([3.0, -2.0], n // 2)})
    sd, src = E.county_sd_from_residuals(r, 2.5)
    assert src == "county_backtest_residuals" and sd == pytest.approx(2.0, rel=0.15)
    assert E.county_sd_from_residuals(r.head(10), 2.5) == (2.5, "config_default")


# ---------------------------------------------------------------- covariance
def test_correlation_matrices_are_valid():
    for c in (C.region_corr(0.3), C.group_corr()):
        assert np.allclose(np.diag(c), 1.0) and np.linalg.eigvalsh(c).min() > 0
    g = C.group_corr()
    assert g[GROUPS.index("black"), GROUPS.index("hispanic")] == pytest.approx(0.3, abs=0.02)
    assert g[GROUPS.index("wnh_college"), GROUPS.index("wnh_noncollege")] == pytest.approx(-0.3, abs=0.02)
    r = C.region_corr(0.3)
    assert r[REGIONS.index("northeast"), REGIONS.index("midwest")] == pytest.approx(0.3, abs=0.02)
    assert r[REGIONS.index("northeast"), REGIONS.index("pacific")] == pytest.approx(0.0, abs=0.05)


def test_cosine_similarity_and_state_corr():
    comp = pd.DataFrame({"wnh": [.8, .8, .3], "black": [.1, .1, .4], "hisp": [.1, .1, .3]}, index=["A", "B", "C"])
    s = C.cosine_similarity(comp)
    assert s.loc["A", "B"] == pytest.approx(1.0) and 0 < s.loc["A", "C"] < 1 and (s.to_numpy() >= 0).all()
    c = C.state_correlation(s, 0.2, ["A", "B", "C"])
    assert c[0, 1] == pytest.approx(0.2, abs=0.02) and c[0, 2] < c[0, 1]
    same = C.state_correlation(s, 0.2, ["A", "A", "C"])
    assert same[0, 1] > 0.5


# ---------------------------------------------------------------- simulation
def _inputs(cfg, with_counties=True, n_states=6, per=8):
    em = E.default_error_model(cfg)
    st = pd.DataFrame({"m_hat": np.linspace(-9, 9, n_states), "polled": [True, False] * (n_states // 2),
                       "n_eff": [4.0, 0.0] * (n_states // 2), "state_po": [f"S{i}" for i in range(n_states)]},
                      index=[f"S{i}" for i in range(n_states)])
    cty = None
    if with_counties:
        rows = []
        for s in st.index:
            om = RNG.uniform(1e3, 1e5, per)
            mh = st.m_hat[s] + RNG.normal(0, 8, per)
            mh += st.m_hat[s] - np.average(mh, weights=om)  # roll up exactly to the state margin
            rows += [{"geoid": f"{s}{i:03d}", "state_po": s, "region": REGIONS[(i + len(s)) % 5], "m_hat": mh[i],
                      "omega": om[i]} for i in range(per)]
        cty = pd.DataFrame(rows)
    return build_inputs(st, em, cfg, None, cty), em


def test_state_margin_is_nu_weighted_county_margin(cfg):
    """M_s = sum nu_i M_i exactly (up to int8 quantisation): the county term is zero-sum within a state."""
    inp, em = _inputs(cfg)
    res = S.simulate(inp, em, 2000, 1, 0.3, chunk=700)
    cty = inp.counties
    dev = res.county_dev.astype(float) / S.Q
    for k, u in enumerate(res.units):
        m = (cty.unit == u).to_numpy()
        got = res.m_hat[k] + dev[:, m] @ cty.nu[m].to_numpy()
        ok = (np.abs(res.county_dev[:, m]) < 127).all(axis=1)  # drop draws where any county saturated (+-12.7)
        assert ok.mean() > 0.9
        assert np.abs(got - res.margins[:, k])[ok].max() < 0.06  # int8 rounding only


def test_unit_variance_scaling_and_moments(cfg):
    inp, em = _inputs(cfg, with_counties=False)
    res = S.simulate(inp, em, 40000, 5, 0.3)
    sd_expect = np.sqrt(em.national**2 + em.region**2 * (inp.region_share.to_numpy() ** 2).sum(axis=1)
                        + inp.units.sd_state.to_numpy() ** 2)
    sd = res.margins.std(axis=0)
    assert np.all(sd > 0.85 * sd_expect) and np.all(sd < 1.2 * sd_expect)  # + a small group term
    assert res.margins.mean(axis=0) == pytest.approx(res.m_hat, abs=0.15)
    assert abs(res.e_nat.mean()) < 1e-9  # antithetic pairs on e_nat
    assert res.e_nat.std() == pytest.approx(em.national, rel=0.05)


def test_heavy_tails(cfg):
    inp, em = _inputs(cfg, with_counties=False)
    res = S.simulate(inp, em, 40000, 8, 0.3)
    z = (res.e_nat) / em.national
    assert (np.abs(z) > 4).mean() > 5e-4  # t(6) puts ~0.8% beyond 4 sd-equivalents of a unit-variance normal's 6e-5


def test_seed_reproducible_and_even_draws(cfg):
    inp, em = _inputs(cfg, with_counties=False)
    a = S.simulate(inp, em, 1000, 3, 0.3).margins
    b = S.simulate(inp, em, 1000, 3, 0.3).margins
    assert np.array_equal(a, b)
    assert S.simulate(inp, em, 999, 3, 0.3).margins.shape[0] == 1000


def test_correlation_between_similar_states_exceeds_dissimilar(cfg):
    em = E.default_error_model(cfg)
    st = pd.DataFrame({"m_hat": [0.0] * 3, "polled": [True] * 3, "n_eff": [4.0] * 3, "state_po": ["A", "B", "C"]},
                      index=["A", "B", "C"])
    st.loc["A", "state_po"] = "AA"
    comp = pd.DataFrame({"white": [.8, .8, .2], "black": [.1, .1, .6], "hisp": [.1, .1, .2]}, index=["AA", "B", "C"])
    inp = build_inputs(st, em, cfg)
    sim = C.cosine_similarity(comp)
    inp.corr_state = C.state_correlation(pd.DataFrame(sim.to_numpy(), index=st.index, columns=st.index), 0.9)
    res = S.simulate(inp, em, 40000, 2, 0.3)
    c = np.corrcoef(res.margins.T)
    assert c[0, 1] > c[0, 2]


# ---------------------------------------------------------------- outputs
def _res(margins, m_hat=None, units=None):
    margins = np.asarray(margins, dtype=np.float32)
    units = units or [f"S{i}" for i in range(margins.shape[1])]
    return S.SimResult(units, margins, np.zeros(margins.shape[1]) if m_hat is None else m_hat)


def test_seat_distribution_and_control(cfg):
    m = np.array([[1, 1, -1], [1, -1, -1], [1, 1, 1], [-1, -1, -1]], dtype=float)
    d = O.seat_distribution(_res(m), h_d=48, threshold=50)
    assert d["pmf"] == {48: 0.25, 49: 0.25, 50: 0.25, 51: 0.25}
    assert d["p_control"] == pytest.approx(0.5)
    assert sum(d["pmf"].values()) == pytest.approx(1.0)


def test_tipping_point_frequencies():
    m = np.array([[5, 3, 1, -2], [4, 6, -1, -3], [2, 1, 0.5, 0.1], [-1, 9, 3, 2]], dtype=float)
    # D needs 3 of 4 contested seats (51 - 48): the third most Democratic state tips (S2 in three draws, S3 in the last)
    assert O.tipping_frequencies(_res(m), h_d=48, threshold=51) == {"S2": 0.75, "S3": 0.25}
    assert sum(O.tipping_frequencies(_res(m), h_d=48, threshold=51).values()) == pytest.approx(1.0)
    assert O.tipping_frequencies(_res(m), h_d=40, threshold=51) == {}  # unreachable


def test_h_d_from_races():
    races = pd.DataFrame({"incumbent_party": ["R"] * 22 + ["D"] * 13})
    assert O.d_seats_not_up(races, 47) == 34


def test_interval_and_pwin_tables(cfg):
    rng = np.random.default_rng(0)
    res = _res(rng.normal(2.0, 4.0, (20000, 2)), m_hat=np.array([2.0, 2.0]))
    t = O.state_table(res, [0.1, 0.9])
    assert t.p_dside_win.iloc[0] == pytest.approx(0.69, abs=0.02)
    assert t.hi.iloc[0] - t.lo.iloc[0] == pytest.approx(2 * 1.2816 * 4.0, rel=0.03)


def test_county_table_and_npz_roundtrip(cfg, tmp_path):
    inp, em = _inputs(cfg)
    res = S.simulate(inp, em, 400, 4, 0.3)
    ct = O.county_table(res, cfg.sim.interval)
    assert (ct.lo <= ct.m_hat + 1e-9).all() and (ct.hi >= ct.m_hat - 1e-9).all() and ct.p_dside_win.between(0, 1).all()
    races = pd.DataFrame({"incumbent_party": ["R"] * 3 + ["D"] * 3})
    sm = O.summarize(res, races, cfg)
    O.write_outputs(res, sm, races, cfg, tmp_path, em.as_dict())
    z = np.load(tmp_path / "sim_draws.npz")
    assert z["county_dev_x10"].dtype == np.int8 and z["county_dev_x10"].shape == res.county_dev.shape
    assert (tmp_path / "sim_summary.json").exists() and (tmp_path / "correlations.json").exists()


# ---------------------------------------------------------------- roll-up and summary merge
def _rollup_frames():
    cty = pd.DataFrame({"state_po": ["A", "A", "B"], "m_hat": [10.0, -4.0, 3.0], "omega": [1.0, 3.0, 5.0]})
    exp = (10 - 12) / 4  # -0.5
    comp = pd.DataFrame({"state_po": ["A", "B"], "m0": [-1.0, 1.0], "swing": [0.3, 1.0], "T": [0.1, 0.5], "E": [0.1, 0.5]})
    return cty, comp, exp


def test_rollup_identity_passes_and_fails():
    cty, comp, exp = _rollup_frames()
    assert exp == pytest.approx(-0.5)
    assert check_rollup(cty, comp).abs_err.max() < 1e-6
    comp.loc[0, "E"] += 0.01
    with pytest.raises(AssertionError, match="roll-up"):
        check_rollup(cty, comp)


def test_add_simulation_checks_agreement():
    summary = {"races": [{"state": "PA", "proj_margin": 1.234}]}
    sim = {"states": {"PA": {"p_dside_win": 0.6, "m_hat": 1.2341, "lo": -3.0, "hi": 5.0}}, "n_draws": 10,
           "interval": [0.1, 0.9], "seats": {}, "tipping": {}}
    out = add_simulation(summary, sim)
    assert out["races"][0]["interval80"] == [-3.0, 5.0] and out["races"][0]["p_dside_win"] == 0.6
    sim["states"]["PA"]["m_hat"] = 3.0
    with pytest.raises(AssertionError):
        add_simulation({"races": [{"state": "PA", "proj_margin": 1.234}]}, sim)


# ---------------------------------------------------------------- calibration metrics
def test_reliability_and_logloss():
    p = np.array([0.05, 0.15, 0.95, 0.95])
    y = np.array([0.0, 0.0, 1.0, 1.0])
    rel = SB.reliability(p, y)
    assert len(rel) == 10 and sum(b["n"] for b in rel) == 4 and rel[9]["observed"] == 1.0
    assert SB.log_loss(np.array([0.5]), np.array([1.0])) == pytest.approx(np.log(2))
    assert SB.gate({"brier": 0.08, "coverage80": 0.8}) == {"brier<=0.10": True, "coverage80_in_0.70-0.90": True}


def test_sim_metrics_perfectly_calibrated_when_truth_drawn_from_model(cfg):
    """If actuals are drawn from the same error model, coverage ~0.80 and Brier beats a coin flip."""
    n = 400
    rng = np.random.default_rng(9)
    m_hat = rng.uniform(-12, 12, n)
    em = E.default_error_model(cfg)
    st = pd.DataFrame({"m_hat": m_hat, "polled": True, "n_eff": 4.0, "state_po": [f"S{i}" for i in range(n)]},
                      index=[f"S{i}" for i in range(n)])
    inp = build_inputs(st, em, cfg)
    inp.corr_state = np.eye(n)
    res = S.simulate(inp, em, 4000, 6, 0.3)
    sd = res.margins.std(axis=0)
    df = pd.DataFrame({"contest": st.index, "actual_margin": m_hat + rng.normal(0, 1, n) * sd})
    m = SB.sim_metrics(df, res, [0.1, 0.9])
    assert 0.70 <= m["coverage80"] <= 0.90 and m["brier"] < 0.25
