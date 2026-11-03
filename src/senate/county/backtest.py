"""County-level backtest of the swing construction vs the uniform-swing baseline (plan §7.3, §7.4)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import ROOT, Settings, load_config
from ..ei import inputs as I
from ..ei.groups import GROUPS
from ..ingest._base import processed_dir
from .construct import build_state, omega_groups, regional_weights

OUTPUT = ROOT / "output" / "county"


def weighted_rmse(err: np.ndarray, w: np.ndarray | None = None) -> float:
    w = np.ones_like(err) if w is None else w
    return float(np.sqrt((w * err**2).sum() / w.sum()))


def backtest_states(m0: pd.Series, m1: pd.Series, w: pd.Series, state_of: pd.Series, omega: pd.DataFrame,
                    region: pd.Series, delta: pd.DataFrame, persistence: float, max_tilt: float = 6.0
                    ) -> pd.DataFrame:
    """For each state: true state swing S_s = nu-weighted (m1 - m0); county predictions with the group-pattern tilt
    (deltas scaled by `persistence`) vs the uniform baseline s_i = S_s. Returns one row per county."""
    reg_w = regional_weights(omega, region)
    d = delta * persistence
    rows = []
    for st in sorted(state_of.unique()):
        ids = state_of.index[state_of == st]
        nu = w.reindex(ids) / w.reindex(ids).sum()
        S = float((nu * (m1.reindex(ids) - m0.reindex(ids))).sum())
        counties = pd.DataFrame({"m0": m0.reindex(ids), "region": region.reindex(ids)})
        res = build_state(st, S, counties, omega.reindex(ids), d, reg_w, "ok", None, 0.0, max_tilt)
        res["actual"] = m1.reindex(ids).to_numpy()
        res["w"] = w.reindex(ids).to_numpy()
        res["uniform"] = res.m0 + S
        res["state_po"] = st
        rows.append(res)
    return pd.concat(rows, ignore_index=True)


def summarize(bt: pd.DataFrame) -> dict:
    e_m, e_u = (bt.m_hat - bt.actual).to_numpy(), (bt.uniform - bt.actual).to_numpy()
    w = bt.w.to_numpy(float)
    out = {"n_counties": int(len(bt)), "rmse_model_weighted": weighted_rmse(e_m, w),
           "rmse_uniform_weighted": weighted_rmse(e_u, w), "rmse_model_unweighted": weighted_rmse(e_m),
           "rmse_uniform_unweighted": weighted_rmse(e_u)}
    out["improvement_weighted"] = out["rmse_uniform_weighted"] - out["rmse_model_weighted"]
    out["passes_beats_uniform_by_0.3"] = bool(out["improvement_weighted"] >= 0.3)
    out["passes_max_5.5"] = bool(out["rmse_model_weighted"] <= 5.5)
    return out


def run_county_backtest(cfg: Settings | None = None) -> dict:
    """2020 -> 2024 presidential county shifts, given the true state swing, with the shift-EI pattern (in-sample).

    This checks that the EI group-pattern layer adds county-level information over uniform swing. It is IN-SAMPLE
    (the pattern was fit on the same two elections) and is not the plan's out-of-sample §7.1 county Senate test, which
    needs county-level Senate truth (MEDSL county Senate 1976-2024) that is not in the repo."""
    cfg = cfg or load_config()
    proc = processed_dir()
    inp = I.load_inputs(cfg)
    ei = pd.read_parquet(proc / "ei_group_vote.parquet")
    shift = pd.read_parquet(proc / "ei_shift_2024.parquet")
    geo = inp["geo"].set_index("geoid")
    v24, v20 = inp["v24"].set_index("geoid"), inp["v20"].set_index("geoid")
    ids = geo.index[geo.index.isin(set(ei.geoid))]
    geo = geo.loc[ids]
    m = lambda v: 100.0 * (v.votes_d - v.votes_r) / (v.votes_d + v.votes_r)  # noqa: E731
    eig = ei.assign(state_po=ei.geoid.map(geo.state_po)).astype({"group": str})
    omega = omega_groups(eig[["geoid", "state_po", "group", "n_group"]], cfg.turnout.dropoff, GROUPS)
    delta = shift.pivot(index="region", columns="group", values="delta_mean")[GROUPS]
    bt = backtest_states(m(v20).reindex(ids), m(v24).reindex(ids), (v24.votes_d + v24.votes_r).reindex(ids),
                         geo.state_po, omega, geo.region, delta, cfg.ei.pattern_persistence, cfg.county.max_tilt)
    res = summarize(bt)
    res["in_sample"] = True
    OUTPUT.mkdir(parents=True, exist_ok=True)
    bt.to_parquet(OUTPUT / "backtest_2020_2024_county_errors.parquet", index=False)
    pd.Series(res).to_json(OUTPUT / "backtest_2020_2024_summary.json", indent=2)
    return res
