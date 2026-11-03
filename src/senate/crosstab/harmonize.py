"""Harmonise poll crosstab cells to EI groups and swing observations z_kg (plan §6.7)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..ei.groups import _STATE_REGION, GROUPS

NONWHITE = ["black", "hispanic", "asian", "other"]
AGE_BINS = ["18-29", "30-44", "45-64", "65+"]
AGE_MID = {"18-29": 24.0, "30-44": 37.0, "45-64": 54.5, "65+": 75.0}
AGE_SD_YEARS = 17.5
STATE_MIN_N = 200  # state-level crosstabs only for n_group >= 200 (plan §6.7)

CELL_COLS = ["poll_id", "geography", "group", "y", "b", "z", "var", "n_group", "nonwhite"]


def baseline_table(ei: pd.DataFrame, geo: pd.DataFrame, level: str) -> pd.DataFrame:
    """EI group margin baselines at national/region/state level: geography, group, b (margin pts), b_sd.

    ei: ei_group_vote (geoid, group, theta_mean, theta_p10, theta_p90, n_group); geo: geoid, state_po, region.
    b = 100(2*theta-1) with n-weighted pooling; b_sd from the posterior p10-p90 width (independent county errors).
    """
    d = ei.merge(geo[["geoid", "state_po", "region"]], on="geoid", how="inner")
    key = {"national": None, "region": "region", "state": "state_po"}[level]
    d["sd"] = (d.theta_p90 - d.theta_p10) / 2.5631  # normal approx of the 10-90 interval
    d["w"] = d.n_group
    d["_k"] = "national" if key is None else d[key]
    d["wt"] = d.theta_mean * d.w
    d["wsd2"] = (d.sd * d.w) ** 2
    g = d.groupby(["_k", "group"]).agg(wt=("wt", "sum"), w=("w", "sum"), wsd2=("wsd2", "sum"))
    out = pd.DataFrame({"b": 100 * (2 * g.wt / g.w - 1), "b_sd": 200 * np.sqrt(g.wsd2) / g.w}).reset_index()
    return out.rename(columns={"_k": "geography"})


def nonwhite_baseline(base: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    """Combined 'nonwhite' baseline per geography: n-weighted mean of the four non-white group baselines."""
    d = base[base.group.isin(NONWHITE)].merge(weights, on=["geography", "group"], how="left")
    d["w"] = d.w.fillna(1.0)
    g = d.groupby("geography").apply(
        lambda x: pd.Series({"b": np.average(x.b, weights=x.w),
                             "b_sd": np.sqrt(np.sum((x.w / x.w.sum()) ** 2 * x.b_sd**2))}), include_groups=False)
    return g.reset_index()


def geography_region(geography: str) -> str:
    """'national' stays national; a state_po maps to its region; region names pass through."""
    if geography == "national" or geography in set(_STATE_REGION.values()):
        return geography
    return _STATE_REGION.get(geography, "national")


def harmonize(cx: pd.DataFrame, base: dict[str, pd.DataFrame], group_weights: pd.DataFrame, deff: float,
              min_n: int = 75) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Race/education cells -> observation table; age cells returned separately for the gradient model.

    base: {'national': ..., 'region': ..., 'state': ...} from baseline_table. group_weights: geography, group, w
    (n_group, used to split 'nonwhite' cells). Returns (cells, age_cells). Cells follow
    z = y - b, Var(z) = (100*2*sqrt(p(1-p)) / sqrt(n/deff))^2 + b_sd^2 ('nonwhite': variance x2).
    """
    rows, age_rows = [], []
    for r in cx.itertuples():
        if r.n_group < min_n:
            continue
        if r.group_dim == "age" or r.group_value in AGE_BINS:
            age_rows.append(r._asdict())
            continue
        if r.group_dim in ("gender",) or r.group_value in ("male", "female"):
            continue  # shown in methodology only (county gender CVAP ~50/50)
        geo = r.geography
        if geo != "national" and r.geography in _STATE_REGION and r.n_group < STATE_MIN_N:
            continue
        lvl = "national" if geo == "national" else ("state" if geo in _STATE_REGION else "region")
        p = r.dside_pct / (r.dside_pct + r.rside_pct)
        samp_var = (100 * 2 * np.sqrt(p * (1 - p)) / np.sqrt(r.n_group / deff)) ** 2
        y = 100.0 * (r.dside_pct - r.rside_pct) / (r.dside_pct + r.rside_pct)
        bt = base[lvl]
        if r.group_value == "nonwhite":
            nb = nonwhite_baseline(bt[bt.geography == geo], group_weights[group_weights.geography == geo])
            if nb.empty:
                continue
            w = group_weights[(group_weights.geography == geo) & group_weights.group.isin(NONWHITE)]
            tot = w.w.sum() or 1.0
            for g in NONWHITE:
                share = float(w.loc[w.group == g, "w"].sum() / tot) if tot else 0.25
                rows.append(dict(poll_id=r.poll_id, geography=geo, group=g, y=y, b=nb.b.iloc[0], z=y - nb.b.iloc[0],
                                 var=2 * (samp_var + nb.b_sd.iloc[0] ** 2), n_group=r.n_group * share, nonwhite=True))
            continue
        if r.group_value not in GROUPS:
            continue
        b = bt[(bt.geography == geo) & (bt.group == r.group_value)]
        if b.empty:
            continue
        rows.append(dict(poll_id=r.poll_id, geography=geo, group=r.group_value, y=y, b=float(b.b.iloc[0]),
                         z=y - float(b.b.iloc[0]), var=samp_var + float(b.b_sd.iloc[0]) ** 2,
                         n_group=r.n_group, nonwhite=False))
    cells = pd.DataFrame(rows, columns=CELL_COLS)
    return cells, pd.DataFrame(age_rows)


def age_gradient(age_cells: pd.DataFrame, age_baseline: pd.DataFrame | None, sd_young_share: float = 0.05
                 ) -> dict:
    """beta_age: swing gap between 18-44 and 45+ voters (pts) x sd of the county 18-44 share.

    Needs an age-level baseline (validated-voter rows with group_dim='age', d_share_2p) so the poll margin can be
    turned into a swing. Without one (or without age cells) the gradient is 0 and the reason is reported.
    """
    if age_cells is None or age_cells.empty:
        return {"age_gradient_per_sd": 0.0, "n_cells": 0, "reason": "no age cells"}
    if age_baseline is None or age_baseline.empty:
        return {"age_gradient_per_sd": 0.0, "n_cells": int(len(age_cells)), "reason": "no age baseline"}
    bm = {r.group_value: 100 * (2 * r.d_share_2p - 1) for r in age_baseline.itertuples()}
    a = age_cells.copy()
    a["y"] = 100.0 * (a.dside_pct - a.rside_pct) / (a.dside_pct + a.rside_pct)
    a["z"] = a.y - a.group_value.map(bm)
    a = a.dropna(subset=["z"])
    if a.empty:
        return {"age_gradient_per_sd": 0.0, "n_cells": 0, "reason": "age labels not in baseline"}
    young = a[a.group_value.isin(["18-29", "30-44"])]
    old = a[a.group_value.isin(["45-64", "65+"])]
    if young.empty or old.empty:
        return {"age_gradient_per_sd": 0.0, "n_cells": int(len(a)), "reason": "need young and old cells"}
    gap = np.average(young.z, weights=young.n_group) - np.average(old.z, weights=old.n_group)
    return {"age_gradient_per_sd": float(gap * sd_young_share), "n_cells": int(len(a)), "reason": "ok"}
