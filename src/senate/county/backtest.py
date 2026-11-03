"""County-level backtest of the swing construction vs the uniform-swing baseline (plan §7.3, §7.4)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import ROOT, Settings, load_config
from ..ei import inputs as I
from ..ei.groups import GROUPS
from ..ingest._base import processed_dir
from .construct import build_state, ei_elasticity, omega_groups
from .urban import classify, urban_terms

OUTPUT = ROOT / "output" / "county"


def weighted_rmse(err: np.ndarray, w: np.ndarray | None = None) -> float:
    w = np.ones_like(err) if w is None else w
    return float(np.sqrt((w * err**2).sum() / w.sum()))


def backtest_states(m0: pd.Series, m1: pd.Series, w: pd.Series, state_of: pd.Series, omega: pd.DataFrame,
                    region: pd.Series, delta: pd.DataFrame, persistence: float, max_tilt: float | None = 6.0,
                    classes: pd.Series | None = None, area_delta: dict[str, float] | None = None,
                    overlap_shrink: tuple[float, float] = (1.0, 1.0),
                    ei_scale: pd.DataFrame | None = None) -> pd.DataFrame:
    """For each state: true state swing S_s = nu-weighted (m1 - m0); county predictions with the group-pattern tilt
    (deltas scaled by `persistence`) vs the uniform baseline s_i = S_s. Returns one row per county."""
    d = delta * persistence
    rows = []
    for st in sorted(state_of.unique()):
        ids = state_of.index[state_of == st]
        nu = w.reindex(ids) / w.reindex(ids).sum()
        S = float((nu * (m1.reindex(ids) - m0.reindex(ids))).sum())
        counties = pd.DataFrame({"m0": m0.reindex(ids), "region": region.reindex(ids)})
        ut = (urban_terms(classes.reindex(ids), w.reindex(ids), area_delta)
              if classes is not None and area_delta else None)
        res = build_state(st, S, counties, omega.reindex(ids), d, "ok", None, 0.0, max_tilt, ut, overlap_shrink,
                          None if ei_scale is None else ei_scale.reindex(ids))
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


def true_group_swings(validated: pd.DataFrame, groups: list[str] = GROUPS, dim: str = "race") -> dict[str, float]:
    """True 2020->2024 national margin swing (pts) per group from validated-voter rows that exist in both years
    (mean of the rows' d_share_2p per year; 200 x change in share). Groups without both years are omitted."""
    out = {}
    v = validated[validated.geography == "national"]
    for g in groups if dim == "race" else ["urban", "suburban", "rural"]:
        a = v[(v.group_value == g) & (v.year == 2020)].d_share_2p.astype(float)
        b = v[(v.group_value == g) & (v.year == 2024)].d_share_2p.astype(float)
        if len(a) and len(b):
            out[g] = 200.0 * (b.mean() - a.mean())
    return out


def run_group_county_backtest(cfg: Settings | None = None, shrink_grid=(0.0, 0.25, 0.5, 0.75, 1.0),
                              max_tilt_grid=(6.0, 8.0, 10.0, 12.0, 15.0, None),
                              kappa_grid=(0.0, 0.5, 1.0, 1.5, 2.0)) -> dict:
    """Task 4 acceptance test: feed the TRUE 2020->2024 group swings (validated-voter rows, both years) into the
    tilt (+ urban/rural term) and compare county RMSE with uniform swing. Picks overlap_shrink.urban and county.max_tilt on grids
    (max_tilt None = no cap).
    Groups with no 2020 and 2024 pair get the all-group mean swing (zero tilt contribution)."""
    cfg = cfg or load_config()
    proc = processed_dir()
    inp = I.load_inputs(cfg)
    ei = pd.read_parquet(proc / "ei_group_vote.parquet")
    val = pd.read_parquet(proc / "validated_voter_priors.parquet")
    geo = inp["geo"].set_index("geoid")
    v24, v20 = inp["v24"].set_index("geoid"), inp["v20"].set_index("geoid")
    ids = geo.index[geo.index.isin(set(ei.geoid))]
    geo = geo.loc[ids]
    m = lambda v: 100.0 * (v.votes_d - v.votes_r) / (v.votes_d + v.votes_r)  # noqa: E731
    eig = ei.assign(state_po=ei.geoid.map(geo.state_po)).astype({"group": str})
    omega = omega_groups(eig[["geoid", "state_po", "group", "n_group"]], cfg.turnout.dropoff, GROUPS)
    sw = true_group_swings(val)
    mean_sw = float(np.mean(list(sw.values()))) if sw else 0.0
    delta = pd.DataFrame({g: sw.get(g, mean_sw) for g in GROUPS}, index=sorted(geo.region.unique()))
    area = true_group_swings(val, dim="area")
    cvap = inp["cvap"].groupby("geoid").cvap.sum()
    nchs_p = ROOT / "data" / "manual" / "nchs_urcs_2023.csv"
    classes, cmethod = classify(ids, cvap, pd.read_csv(nchs_p) if nchs_p.exists() else None)
    args = (m(v20).reindex(ids), m(v24).reindex(ids), (v24.votes_d + v24.votes_r).reindex(ids), geo.state_po, omega,
            geo.region, delta, 1.0, cfg.county.max_tilt)
    out = {"true_group_swings": sw, "true_area_swings": area, "class_method": cmethod, "groups_without_pair":
           [g for g in GROUPS if g not in sw]}
    base = summarize(backtest_states(*args))
    out["uniform_rmse_weighted"] = base["rmse_uniform_weighted"]
    out["tilt_rmse_weighted"] = base["rmse_model_weighted"]
    grid = {}
    for k in shrink_grid:
        bt = backtest_states(*args, classes=classes, area_delta=area, overlap_shrink=(0.0, k))
        grid[k] = summarize(bt)["rmse_model_weighted"]
    out["tilt_urban_rmse_by_shrink"] = grid
    best = min(grid, key=grid.get)
    out["chosen_overlap_shrink_urban"] = best
    out["tilt_urban_rmse_weighted"] = grid[best]
    # max_tilt grid (Cause 5): the tilt goes through the same county_raw_swing as 2026; rows = tilt only / + urban
    cap_args = list(args)
    tilt_grid, urban_grid = {}, {}
    for cap in max_tilt_grid:
        cap_args[-1] = cap
        key = "none" if cap is None else str(cap)
        tilt_grid[key] = summarize(backtest_states(*cap_args))["rmse_model_weighted"]
        urban_grid[key] = summarize(backtest_states(*cap_args, classes=classes, area_delta=area,
                                                    overlap_shrink=(0.0, best)))["rmse_model_weighted"]
    out["tilt_rmse_by_max_tilt"] = tilt_grid
    out["tilt_urban_rmse_by_max_tilt"] = urban_grid
    out["chosen_max_tilt"] = min(urban_grid, key=urban_grid.get)
    # EI elasticity grid: group swings scaled by (theta(1-theta) / state mean)^kappa; theta is the 2024 EI posterior
    # (in-sample for the 2020->24 swing, so treat the chosen kappa as optimistic), at the chosen shrink and cap.
    theta = ei.pivot(index="geoid", columns="group", values="theta_mean").reindex(columns=GROUPS)
    best_cap = None if out["chosen_max_tilt"] == "none" else float(out["chosen_max_tilt"])
    kap, sd_pred = {}, {}
    for k in kappa_grid:
        sc = ei_elasticity(theta, omega, geo.state_po, k)
        bt = backtest_states(*args[:-1], best_cap, classes=classes, area_delta=area, overlap_shrink=(0.0, best),
                             ei_scale=sc)
        kap[str(k)] = summarize(bt)["rmse_model_weighted"]
        sw_pred = (bt.m_hat - bt.m0).to_numpy()
        sd_pred[str(k)] = float(np.sqrt(np.average((sw_pred - np.average(sw_pred, weights=bt.w)) ** 2, weights=bt.w)))
    out["tilt_rmse_by_ei_kappa"] = kap
    out["pred_swing_sd_by_ei_kappa"] = sd_pred
    out["chosen_ei_kappa"] = min(kap, key=kap.get)
    out["age_term"] = "not testable: only the 18-29 bin has 2020 and 2024 validated rows"
    out["beats_uniform"] = bool(min(urban_grid.values()) < base["rmse_uniform_weighted"])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    pd.Series(out, dtype=object).to_json(OUTPUT / "backtest_group_truth_summary.json", indent=2)
    return out
