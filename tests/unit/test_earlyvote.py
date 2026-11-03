"""Early-vote module: days-out alignment, projection, shrink/cap, ev_detail, adapters, backtest (plan §6.9, §11.1)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from senate.earlyvote import compare as C
from senate.earlyvote import weights as W
from senate.earlyvote.backtest import backtest_total_turnout, summarize
from senate.ingest.early_vote import ELECTION_DAY, EV_COLUMNS, StateAdapter, cumulate
from senate.schemas import SCHEMAS


def _rows(state, cycle, dim, cat, final, share_by_day, geoid=None):
    """Long-format cumulative rows: ballots(d) = final * share_by_day(d) for days_out 20..0."""
    r = []
    for d in range(20, -1, -1):
        r.append({"state_po": state, "geoid": geoid, "date": ELECTION_DAY[cycle] - pd.Timedelta(days=d), "days_out": d,
                  "mode": "total", "party": cat if dim == "party" else "all", "age_bin": cat if dim == "age_bin" else "all",
                  "race5": cat if dim == "race5" else "all", "ballots": int(round(final * share_by_day(d))), "cycle": cycle})
    return pd.DataFrame(r)


def frac(d):  # 40% of the final vote is in by day 5; monotone, 0 before day 20, 0.6 at day 0
    return 0.6 * (1 - d / 20) ** 1.5


def _prov(df):
    return df.assign(source="t", retrieved_at=pd.Timestamp("2026-11-02"), source_version="t", data_quality_flag="ok")


def _world(party_final=None, scale26=None):
    """GA-like state: parties D/R, 2022 and 2024 history, finals known; 2026 is `scale26[p]` x the 2022 curve."""
    party_final = party_final or {"D": 1000, "R": 1000}
    scale26 = scale26 or {"D": 1.0, "R": 1.0}
    hist, daily, finals = [], [], []
    for c, mult in ((2022, 1.0), (2024, 1.3)):
        for p, f in party_final.items():
            hist.append(_rows("GA", c, "party", p, f * mult, frac))
            finals.append({"state_po": "GA", "cycle": c, "party": p, "age_bin": "all", "race5": "all",
                           "final_ballots": f * mult})
        hist.append(_rows("GA", c, None, "all", sum(party_final.values()) * mult, frac))
        finals.append({"state_po": "GA", "cycle": c, "party": "all", "age_bin": "all", "race5": "all",
                       "final_ballots": sum(party_final.values()) * mult})
    for p, f in party_final.items():
        daily.append(_rows("GA", 2026, "party", p, f * scale26[p], lambda d: frac(d) if d >= 3 else 0).query("days_out >= 3"))
    daily.append(_rows("GA", 2026, None, "all", sum(f * scale26[p] for p, f in party_final.items()), frac).query("days_out >= 3"))
    return pd.concat(daily, ignore_index=True), pd.concat(hist, ignore_index=True), pd.DataFrame(finals)


def test_earlyvote_days_out_alignment_interpolation():
    days, vals = np.array([5, 3, 1]), np.array([10.0, 30.0, 50.0])
    assert C.cum_at(days, vals, 2) == pytest.approx(40.0)
    assert C.cum_at(days, vals, 4) == pytest.approx(20.0)
    assert C.cum_at(days, vals, 6) == 0.0          # before voting began
    assert np.isnan(C.cum_at(days, vals, 0))       # later than the last observation: unknown, not extrapolated
    assert C.cum_at(days, vals, 3) == 30.0


def test_period_scale_changes_alignment(cfg):
    daily, hist, finals = _world()
    rules = pd.DataFrame([{"state_po": "GA", "cycle": 2022, "early_period_scale": 2.0}])
    a = C.compare_state(daily, hist, "GA", "party", cfg.earlyvote, None, finals)
    b = C.compare_state(daily, hist, "GA", "party", cfg.earlyvote, rules, finals)
    assert a.table.ev_2022.iloc[0] != b.table.ev_2022.iloc[0]
    assert (b.table.ev_2022 < a.table.ev_2022 + 1e-9).all() or (b.table.ev_2022 > 0).all()


def test_projection_recovers_final_when_pattern_repeats(cfg):
    daily, hist, finals = _world(scale26={"D": 1.1, "R": 0.9})
    comp = C.pick(daily, hist, "GA", cfg.earlyvote, None, finals)
    assert comp.dim == "party" and comp.days_out == 3
    t = comp.table.set_index("category")
    assert t.loc["D", "final_hat"] == pytest.approx(1100, rel=0.02)
    assert t.loc["R", "final_hat"] == pytest.approx(900, rel=0.02)
    assert comp.total_ratio[2022] == pytest.approx(1.0, rel=0.02)


def test_earlyvote_party_cycles_exclude_2018(cfg):
    ev = cfg.earlyvote
    w = C.cycle_weights("party", ev, [2018, 2022, 2024])
    assert 2018 not in w and w == pytest.approx({2022: 0.6, 2024: 0.4})
    w2 = C.cycle_weights("age_bin", ev, [2018, 2022, 2024])
    assert set(w2) == {2018, 2022, 2024} and sum(w2.values()) == pytest.approx(1.0)
    # even if 2018 data exist, a party projection never uses it
    daily, hist, finals = _world()
    h18 = pd.concat([_rows("GA", 2018, "party", p, 500, frac) for p in "DR"])
    f18 = pd.DataFrame([{"state_po": "GA", "cycle": 2018, "party": p, "age_bin": "all", "race5": "all",
                         "final_ballots": 500} for p in "DR"])
    comp = C.compare_state(daily, pd.concat([hist, h18]), "GA", "party", ev, None, pd.concat([finals, f18]))
    assert set(comp.table.cycles_used) == {"2022,2024"}
    assert comp.party_level_shift  # 2018 enters only as an informational diagnostic


def _model(n=8, seed=3, gamma=0.5, tilt=1.0):
    r = np.random.default_rng(seed)
    n_ig = pd.DataFrame(r.uniform(1e3, 5e4, (n, 6)), index=[f"13{i:03d}" for i in range(n)], columns=W.GROUPS)
    m0 = pd.Series(400 * (n_ig["black"] / n_ig.sum(axis=1) - 1 / 6), index=n_ig.index)  # margin tracks group mix
    q = pd.DataFrame({g: [0.6, 0.3, 0.05, 0.05] if g.startswith("black") else [0.2, 0.6, 0.1, 0.1] for g in W.GROUPS},
                     index=W.PARTIES)
    psi = pd.Series({"D": 1.0 * tilt, "R": 1.0 / tilt, "O": 1.0, "U": 1.0})
    return W.EVModel(n_ig, m0, "party", psi, q, gamma=gamma)


def test_earlyvote_cap_binding():
    m = _model(tilt=20.0)  # huge psi tilt
    raw = m.margin(m.omega(1.0)) - m.margin(m.n_ig)
    assert abs(raw) > 1.5
    res = W.apply_cap(m, 1.5)
    assert res["cap_binding"] and 0 < res["kappa"] < 1
    assert abs(res["E"]) <= 1.5 + 1e-9 and abs(res["E"]) == pytest.approx(1.5, abs=1e-6)
    assert res["omega"].values.sum() == pytest.approx(m.n_ig.values.sum())  # state total preserved


def test_earlyvote_cap_not_binding_unchanged():
    m = _model(tilt=1.02)
    res = W.apply_cap(m, 1.5)
    assert not res["cap_binding"] and res["kappa"] == 1.0
    assert res["E"] == pytest.approx(res["E_raw"]) and res["E"] != 0.0
    assert np.allclose(res["omega"].values, m.omega(1.0).values)


def test_shrink_halves_log_multiplier():
    psi = pd.Series({"D": 1.44, "R": 0.64})
    s = W.shrink(psi, 0.5)
    assert s["D"] == pytest.approx(1.2) and s["R"] == pytest.approx(0.8)


def test_category_psi_relative_to_baseline():
    psi = W.category_psi(pd.Series({"D": 1100.0, "R": 900.0}), pd.Series({"D": 1000.0, "R": 1000.0}))
    assert psi["D"] > 1 > psi["R"]
    assert (psi * pd.Series({"D": 1000.0, "R": 1000.0})).sum() == pytest.approx(2000.0)  # weights keep total


def test_party_to_group_matrix_columns_sum_to_one():
    comp = pd.DataFrame({"group": ["black", "black", "hispanic"], "party": ["D", "R", "U"], "count": [80, 20, 10]})
    q = W.party_to_group_matrix(comp)
    assert q.sum(axis=0).to_numpy() == pytest.approx(1.0)
    assert q.loc["D", "black"] == pytest.approx(0.8)
    # groups with no data fall back to the all-group mix
    assert q.loc["D", "asian"] == pytest.approx(80 / 110)


def test_earlyvote_total_only_zero_component(cfg):
    from senate.earlyvote.run_earlyvote import state_component

    daily, hist, finals = _world()
    tot = daily[(daily.party == "all")]
    m = _model()
    res = state_component("GA", cfg, tot, hist[hist.party == "all"], m.n_ig, m.m0, None, finals)
    assert res["ev_detail"] == "total_only" and res["dim"] is None
    assert res["E"] == 0.0 and not res["cap_binding"]
    assert np.allclose(res["omega"].values, m.n_ig.values)
    assert res["comparison"].table.final_hat.iloc[0] > 0  # the total-turnout projection still updates


def test_ev_detail_flags(cfg):
    daily, hist, finals = _world()
    assert C.ev_detail(daily.iloc[0:0], "GA", None) == "none"
    comp = C.pick(daily, hist, "GA", cfg.earlyvote, None, finals)
    assert C.ev_detail(daily, "GA", comp) == "full"
    assert C.ev_detail(daily[daily.party == "all"], "GA", None) == "total_only"
    cty = daily[daily.party == "all"].assign(geoid="13121")
    assert C.ev_detail(cty, "GA", None) == "county_only"


def test_county_only_blend_moves_weights_and_respects_cap(cfg):
    m = _model()
    m.dim, m.psi, m.q = None, None, None
    m.blend = pd.Series(np.linspace(0.5, 2.0, len(m.n_ig)), index=m.n_ig.index)
    om = m.omega(1.0)
    assert not np.allclose(om.values, m.n_ig.values)
    assert om.values.sum() == pytest.approx(m.n_ig.values.sum())
    res = W.apply_cap(m, 1e-3)
    assert abs(res["E"]) <= 1e-3 + 1e-12


def test_county_blend_ignores_missing_history():
    b = W.county_blend(pd.Series({"a": 10.0, "b": 5.0}), pd.Series({"a": 5.0, "b": 0.0}))
    assert b["a"] == 2.0 and np.isnan(b["b"])


def test_race_direct_map_applies_to_both_white_groups():
    f = W.group_factors("race5", pd.Series({"white": 0.9, "black": 1.2}), None, W.GROUPS)
    assert f["wnh_college"] == f["wnh_noncollege"] == 0.9 and f["black"] == 1.2 and f["asian"] == 1.0


def test_age_dimension_uses_county_age_shares():
    m = _model()
    m.dim, m.q, m.psi = "age_bin", None, pd.Series({"18-29": 0.8, "65+": 1.2})
    share = pd.DataFrame({"18-29": np.linspace(0.4, 0.1, len(m.n_ig))}, index=m.n_ig.index)
    share["65+"] = 1 - share["18-29"]
    m.age_share = share
    om = m.omega(1.0)
    ratio = om.sum(axis=1) / m.n_ig.sum(axis=1)
    assert ratio.iloc[0] < ratio.iloc[-1]  # youngest county down-weighted relative to the oldest


# ---- ingest ----------------------------------------------------------------------------------------------------------

def _ballots():
    d = pd.to_datetime(["2022-10-20", "2022-10-20", "2022-10-22", "2022-11-08", "2022-11-09"])
    return pd.DataFrame({"date": d, "mode": ["mail", "early_in_person", "mail", "mail", "mail"],
                         "party": ["D", "R", "D", "U", "R"], "age_bin": "30-44", "race5": "white",
                         "geoid": ["37001", "37001", "37003", "37003", "37003"]})


def test_cumulate_monotone_and_aligned():
    out = cumulate(_ballots(), "NC", 2022)
    assert list(out.columns) == EV_COLUMNS
    assert out.days_out.min() == 0 and out.date.max() == ELECTION_DAY[2022]
    assert 2022 == out.cycle.unique()[0]
    tot = out[(out["mode"] == "total") & (out.party == "all") & (out.age_bin == "all") & out.geoid.isna()].sort_values("days_out")
    assert tot[tot.days_out == 0].ballots.iloc[0] == 4  # the post-election-day ballot is dropped
    assert tot[tot.days_out == 19].ballots.iloc[0] == 2
    prov = _prov(out)
    SCHEMAS["early_vote_hist"].validate(prov)  # cumulative and in-schema (2022 cycle)
    assert (out[out.geoid.notna()].groupby("geoid").ballots.max() > 0).all()


def test_schema_rejects_decreasing_cumulative_counts():
    out = _prov(cumulate(_ballots(), "NC", 2022))
    i = out[(out["mode"] == "total") & (out.party == "all") & (out.age_bin == "all") & out.geoid.isna() & (out.days_out == 0)].index[0]
    bad = out.copy()
    bad.loc[i, "ballots"] = 0
    with pytest.raises(Exception):
        SCHEMAS["early_vote_daily"].validate(bad)


def test_adapter_parse_and_layout_change_detector():
    class Fake(StateAdapter):
        state_po = "NC"
        colmap = {"date": "ballot_rtn_dt", "party": "voter_party_code", "age": "age", "race": "race"}

    raw = pd.DataFrame({"ballot_rtn_dt": ["2022-10-20", "2022-10-21"], "voter_party_code": ["DEM", "REP"],
                        "age": [34, 71], "race": ["W", "B"]})
    out = Fake().parse(raw, 2022)
    assert {"D", "R"} <= set(out.party)
    assert {"30-44", "65+"} <= set(out.age_bin) and {"white", "black"} <= set(out.race5)
    with pytest.raises(ValueError, match="layout changed"):
        Fake().parse(raw.rename(columns={"ballot_rtn_dt": "x"}), 2022)


def test_ingest_falls_back_to_manual_csv(dirs):
    from senate.ingest.early_vote import ingest_early_vote

    m = cumulate(_ballots().assign(date=lambda d: d.date + pd.DateOffset(years=4)), "AZ", 2026)
    m.to_csv(dirs["manual"] / "early_vote_AZ.csv", index=False)
    old = cumulate(_ballots(), "AZ", 2022)
    old.to_csv(dirs["manual"] / "early_vote_AZ.csv", mode="a", header=False, index=False)
    daily, hist = ingest_early_vote(["AZ", "NV"])  # NV has no file at all: skipped, never fails the fetch
    assert set(daily.state_po) == {"AZ"} and set(hist.cycle) == {2022}
    assert (daily.data_quality_flag == "manual").all()
    again, _ = ingest_early_vote(["AZ"])           # snapshots append/dedupe rather than duplicate
    assert len(again) == len(daily)


# ---- backtest --------------------------------------------------------------------------------------------------------

def test_backtest_recovers_known_final(cfg):
    hist, finals = [], []
    for c, f in ((2018, 800), (2020, 1500), (2022, 1000), (2024, 1600)):
        hist.append(_rows("GA", c, None, "all", f, frac))
        finals.append({"state_po": "GA", "cycle": c, "party": "all", "age_bin": "all", "race5": "all", "final_ballots": f})
    bt = backtest_total_turnout(pd.concat(hist), pd.DataFrame(finals), cfg, 1, cvap={"GA": 5000.0})
    assert len(bt) == 1 and bt.comparators.iloc[0] == "2018,2020,2024"
    assert abs(bt.err_pts.iloc[0]) < 0.1           # shared curve shape => near-exact projection
    s = summarize(bt)
    assert s["passes_rmse_3pts"] is True and s["n_states"] == 1


def test_backtest_no_data_is_reported_not_faked():
    assert summarize(pd.DataFrame()) == {"status": "no_data", "n_states": 0, "passes_rmse_3pts": None}
