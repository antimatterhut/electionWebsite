"""Poll weights, caps, house effects, LV/RV and averaging (plan §6.2, §11.1)."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from senate.polls import house_effects as HE
from senate.polls import lv_rv
from senate.polls.average import poll_average, run_poll_averages, tidy_senate
from senate.polls.weights import cap_pollster_weights, margin_2p, poll_weights, w_quality, w_sample, w_time

AS_OF = date(2026, 11, 1)


def _polls(margins, pollsters=None, ages=None, n=1000, pop="LV"):
    k = len(margins)
    ages = ages or [3] * k
    return pd.DataFrame({
        "contest": "GA", "pollster": pollsters or [f"P{i}" for i in range(k)], "margin": margins, "n": n,
        "pop": pop, "partisan": False, "matchup_type": "two_way",
        "field_end": [pd.Timestamp(AS_OF) - pd.Timedelta(days=a) for a in ages]})


def test_margin_2p():
    assert margin_2p(52, 48) == pytest.approx(4.0)
    assert margin_2p(45, 35) == pytest.approx(12.5)  # undecideds ignored


def test_poll_weight_time_decay_halflife():
    assert w_time(14, 14.0) == pytest.approx(0.5)
    assert w_time(28, 14.0) == pytest.approx(0.25)


def test_poll_weight_sample_cap(cfg):
    assert w_sample([5000], cfg.polls)[0] == pytest.approx(w_sample([2000], cfg.polls)[0])
    assert w_sample([600], cfg.polls)[0] == pytest.approx(1.0)
    assert w_sample([100], cfg.polls)[0] == pytest.approx(w_sample([300], cfg.polls)[0])  # n_min floor


def test_poll_weight_quality_monotone():
    assert w_quality(0.0) == 0.5 and w_quality(3.0) == 1.0
    assert w_quality(2.0) > w_quality(1.0)


def test_poll_weight_components(cfg):
    p = _polls([5, 5, 5], ["A", "B", "C"])
    p["pop"] = ["LV", "RV", "A"]
    p.loc[1, "partisan"] = True
    p.loc[2, "matchup_type"] = "multi"
    w = poll_weights(p, AS_OF, "senate", cfg.polls, {"a": 3.0})
    assert w.w_pop.tolist() == [1.0, 0.9, 0.75]
    assert w.w_typ.tolist() == [1.0, 0.6, 0.8]
    assert w.w_q[0] == pytest.approx(1.0)  # rating 3.0 -> top quality
    assert w.w_q[1] == pytest.approx(0.5 + 0.5 * 1.0 / 3)  # unrated -> 1.0


def test_pollster_cap_25pct():
    w = np.array([10, 1, 1, 1, 1, 1, 1.0])
    ps = np.array(["big", "a", "b", "c", "d", "e", "f"])
    out, _ = cap_pollster_weights(w, ps, 0.25, 0.5)
    assert out[0] <= 0.25 + 1e-9 and out.sum() == pytest.approx(1.0)


def test_pollster_cap_half_when_few_pollsters():
    out, _ = cap_pollster_weights(np.array([9, 1, 1.0]), np.array(["a", "a", "b"]), 0.25, 0.5)
    assert out[:2].sum() == pytest.approx(0.5) and out[2] == pytest.approx(0.5)


def test_pollster_cap_converges():
    rng = np.random.default_rng(0)
    w = rng.uniform(0.1, 3, 40)
    ps = rng.choice([f"p{i}" for i in range(8)], 40)
    out, iters = cap_pollster_weights(w, ps, 0.25, 0.5)
    assert iters <= 10 and out.sum() == pytest.approx(1.0)
    assert max(out[ps == p].sum() for p in set(ps)) <= 0.25 + 1e-9


def test_average_equal_weights_is_arithmetic_mean(cfg):
    p = _polls([7, 5, 4, 8, 6]).assign(w=1.0)
    avg = poll_average(p, AS_OF, cfg.polls)
    assert avg.margin == pytest.approx(6.0) and avg.n_polls == 5
    assert avg.n_eff == pytest.approx(5.0)
    assert avg.se == pytest.approx(np.sqrt(3.9**2 / 5 + 1.0))


def test_average_empty_is_unavailable(cfg):
    assert not poll_average(_polls([]), AS_OF, cfg.polls).available


def test_duplicate_from_capped_pollster_moves_average_little(cfg):
    base = _polls([4, 5, 6, 7, 5, 6], ["a", "b", "c", "d", "e", "e"]).assign(w=1.0)
    outlier = base.iloc[[5]].assign(margin=7.0)  # another poll from the capped pollster 'e', 1 pt above the mean
    dup = pd.concat([base, outlier], ignore_index=True)
    shift = abs(poll_average(dup, AS_OF, cfg.polls).margin - poll_average(base, AS_OF, cfg.polls).margin)
    assert shift <= 0.2


def test_house_effects_sum_zero(cfg):
    rows = []
    for c in ("GB", "GA", "MI"):
        for p, bias in [("A", 2.0), ("B", -1.0), ("C", 0.0), ("D", 1.0)] * 2:
            rows.append({"contest": c, "pollster": p, "margin": 5 + bias, "w": 1.0})
    h = HE.estimate_house_effects(pd.DataFrame(rows), cfg.polls.house_effect)
    assert sum(h.values()) == pytest.approx(0.0, abs=1e-9)  # every pollster has equal volume here
    assert h["A"] > h["B"]


def test_house_effects_shrinkage(cfg):
    rows = [{"contest": "GB", "pollster": f"P{i}", "margin": 5.0, "w": 1.0} for i in range(6)]
    rows += [{"contest": "GB", "pollster": "Solo", "margin": 9.0, "w": 1.0}]
    h = HE.estimate_house_effects(pd.DataFrame(rows), cfg.polls.house_effect, min_polls=1)
    raw = 9.0 - np.average([5] * 6 + [9])
    assert 0 < abs(h["Solo"]) < abs(raw) + 1e-9


def test_house_effects_min_polls_and_clip(cfg):
    rows = [{"contest": "GB", "pollster": "Few", "margin": 40.0, "w": 1.0}] * 2
    rows += [{"contest": "GB", "pollster": f"P{i}", "margin": 0.0, "w": 1.0} for i in range(30)]
    h = HE.estimate_house_effects(pd.DataFrame(rows), cfg.polls.house_effect)
    assert h["Few"] == 0.0  # below min_polls = 3
    rows += [{"contest": "GB", "pollster": "Many", "margin": 60.0, "w": 5.0}] * 6
    assert abs(HE.estimate_house_effects(pd.DataFrame(rows), cfg.polls.house_effect)["Many"]) <= 4.0 + 1e-9


def test_poll_pop_adjustment_lv_rv(cfg):
    pairs = []
    for i in range(10):
        pairs += [{"contest": "GB", "pollster": f"P{i}", "field_end": i, "pop": "LV", "margin": 3.0},
                  {"contest": "GB", "pollster": f"P{i}", "field_end": i, "pop": "RV", "margin": 1.0}]
    delta, n = lv_rv.estimate_delta_lv(pd.DataFrame(pairs), cfg.polls.lv_rv)
    assert n == 10 and delta == pytest.approx(10 * 2.0 / 15)  # shrunk toward 0 with k = 5
    adj = lv_rv.adjust_population(pd.DataFrame({"pop": ["LV", "RV", "A"]}), delta)
    assert adj.delta.tolist() == pytest.approx([0.0, delta, 1.5 * delta])


def test_lv_rv_prior_until_min_pairs(cfg):
    few = pd.DataFrame([{"contest": "GB", "pollster": "P", "field_end": 1, "pop": "LV", "margin": 9.0},
                        {"contest": "GB", "pollster": "P", "field_end": 1, "pop": "RV", "margin": 1.0}])
    assert lv_rv.estimate_delta_lv(few, cfg.polls.lv_rv) == (0.0, 1)


def test_rcv_final_round_conversion():
    polls = pd.DataFrame({
        "state_po": ["ME", "ME", "TX"], "matchup_type": ["multi", "rcv_final", "multi"],
        "dside_pct": [44.0, 50.0, 44.0], "rside_pct": [40.0, 46.0, 40.0],
        "other_pct": [10.0, None, 10.0], "field_end": pd.Timestamp(AS_OF), "partisan": False})
    t = tidy_senate(polls, {"ME"}, 0.75)
    assert t.margin[0] == pytest.approx(margin_2p(44 + 7.5, 40 + 2.5))  # minor-candidate transfers (75% to D-side)
    assert t.margin[1] == pytest.approx(margin_2p(50, 46))  # explicit final round used as is
    assert t.margin[2] == pytest.approx(margin_2p(44, 40))  # non-RCV state: plain two-party conversion


def test_run_poll_averages_ignores_future_polls(cfg):
    g = pd.DataFrame({"pollster": ["A", "B"], "field_end": [pd.Timestamp("2026-10-30"), pd.Timestamp("2026-11-05")],
                      "n": 1000, "pop": "LV", "d_pct": [50.0, 80.0], "r_pct": [45.0, 10.0], "partisan": False})
    s = pd.DataFrame({"state_po": ["GA"], "pollster": ["A"], "field_end": [pd.Timestamp("2026-10-30")], "n": 800,
                      "pop": "LV", "dside_pct": [50.0], "rside_pct": [45.0], "other_pct": [None],
                      "matchup_type": "two_way", "partisan": False})
    res = run_poll_averages(g, s, AS_OF, cfg, {})
    assert res.generic.n_polls == 1 and res.generic.margin == pytest.approx(margin_2p(50, 45))
    assert res.states["GA"].margin == pytest.approx(margin_2p(50, 45))
