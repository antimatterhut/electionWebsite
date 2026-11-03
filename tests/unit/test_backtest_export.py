"""Backtest metrics, summary export identity and committed backtest inputs."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from senate.backtest import metrics as M
from senate.backtest.run_backtest import CYCLES, DATA, load_cycle, run_cycle
from senate.export.to_json import build_summary, write_summary
from senate.swing.baseline import baseline_margin


def test_rmse_bias_brier():
    err = np.array([3.0, -4.0])
    assert M.rmse(err) == pytest.approx(np.sqrt(12.5)) and M.bias(err) == pytest.approx(-0.5)
    assert M.brier(np.array([1.0, 0.0]), np.array([1, 0])) == 0.0
    assert M.brier(np.array([0.5]), np.array([1])) == pytest.approx(0.25)
    p = M.provisional_win_prob(np.array([0.0, 100.0]), 5.0)
    assert p[0] == pytest.approx(0.5) and p[1] == pytest.approx(1.0)


def test_coverage80_matches_normal():
    rng = np.random.default_rng(1)
    proj = np.zeros(20000)
    actual = rng.normal(0, 5.0, 20000)
    assert M.coverage80(proj, actual, 5.0) == pytest.approx(0.8, abs=0.01)


def test_committed_truth_spot_checks():
    ga = pd.read_csv(DATA / "2022" / "senate_truth.csv").set_index("state_po").loc["GA"]
    assert (ga.votes_d, ga.votes_r) == (1946117, 1908442)
    pa18 = pd.read_csv(DATA / "2018" / "senate_truth.csv").set_index("state_po").loc["PA"]
    assert baseline_margin(pa18.votes_d, pa18.votes_r) == pytest.approx(13.3, abs=0.1)


def test_committed_baselines_match_certified_totals():
    for y, (d, r) in {2020: (81.28e6, 74.22e6), 2016: (65.85e6, 62.98e6)}.items():
        s = pd.read_csv(DATA / f"pres_state_{y}.csv")
        assert len(s) == 50
        assert s.votes_d.sum() == pytest.approx(d, rel=0.02) and s.votes_r.sum() == pytest.approx(r, rel=0.01)
    ga = pd.read_csv(DATA / "pres_state_2024.csv").set_index("state_po").loc["GA"]
    assert (ga.votes_d, ga.votes_r) == (2548017, 2663117)  # plan section 6.1 worked example


@pytest.mark.parametrize("cycle", [2018, 2022])
def test_backtest_uses_no_polls_after_cutoff(cfg, cycle):
    data = load_cycle(cycle)
    df, nat = run_cycle(cycle, cfg, data=data)
    assert nat["as_of"] < str(CYCLES[cycle]["election_day"])
    assert len(df) == len(data["truth"])
    assert np.isfinite(df.proj_margin).all()
    # identity: projection = baseline + swing
    assert (df.proj_margin - df.m0 - df.swing).abs().max() < 1e-9


def test_summary_identity_and_json(tmp_path):
    states = pd.DataFrame([{"contest": "GA", "state_po": "GA", "m0": -2.2, "polled": True, "poll_margin": 6.0,
                            "n_polls": 5, "n_eff": 3.8, "s_poll": 8.2, "s_nat": 10.5, "swing": 9.7333,
                            "swing_source": "combined", "market_weight": 0.0, "proj_margin": -2.2 + 9.7333}])
    races = pd.DataFrame([{"state_po": "GA", "class": "2", "incumbent": "Ossoff", "incumbent_party": "D",
                           "special": "false", "dside_name": "Jon Ossoff", "dside_party": "D",
                           "dside_endorsed_by_dem": "false", "rside_name": "Mike Collins", "rside_party": "R",
                           "rcv": "false", "notes": ""}])
    nat = {"as_of": "2026-11-02", "gb_margin": 9.0, "gb_source": "own_average", "gb_n_polls": 38, "gb_n_eff": 21.4,
           "gb_se": 1.1, "npv_baseline": -1.5, "s_nat": 10.5}
    summ = build_summary(nat, states, races, 2.0, 1.0, run_id="t")
    p = write_summary(summ, tmp_path / "summary.json")
    got = json.loads(p.read_text())
    r = got["races"][0]
    assert r["proj_margin"] == pytest.approx(r["pres2024_margin"] + r["components"]["state_swing"], abs=0.05)
    assert got["weights"] == {"national": 2.0, "state_poll": 1.0} and r["swing_source"] == "combined"
    bad = states.assign(proj_margin=0.0)
    with pytest.raises(AssertionError):
        build_summary(nat, bad, races, 2.0, 1.0)
