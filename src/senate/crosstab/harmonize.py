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

CELL_COLS = ["poll_id", "geography", "group", "y", "b", "z", "var", "n_group", "nonwhite", "b_source"]


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


def validated_baseline(validated: pd.DataFrame | None, geography: str, group: str, sd_floor_logit: float = 0.10,
                       year: int = 2024, group_dim: str | None = None) -> tuple[float, float] | None:
    """(b, b_sd) in margin points from the validated-voter studies for one group and geography, or None.

    b = 100(2 mean(d_share_2p) - 1); b_sd = 200 * spread across studies of d_share_2p, floored at the equivalent of
    `sd_floor_logit` on the logit scale (p(1-p) * floor) so a single study is not treated as exact."""
    if validated is None or not len(validated):
        return None
    q = validated[(validated.year == year) & (validated.geography == geography) & (validated.group_value == group)]
    if group_dim is not None:
        q = q[q.group_dim == group_dim]
    if not len(q):
        return None
    m = q.d_share_2p.astype(float)
    p = float(m.mean())
    sd = max(float(m.std(ddof=0)) if len(m) > 1 else 0.0, p * (1 - p) * sd_floor_logit)
    return 100.0 * (2 * p - 1), 200.0 * sd


def ei_baseline_sd_floor(national_ei: pd.DataFrame, validated: pd.DataFrame | None, sd_floor_logit: float = 0.10
                         ) -> float:
    """RMS gap (margin pts) between EI's national group baselines and the validated-voter 2024 means.

    EI's own posterior b_sd ignores model misspecification (county data identify the white education split and the
    smaller groups weakly), so it is floored at this measured discrepancy. 0 when no group has a validated baseline."""
    gaps = []
    for r in national_ei.itertuples():
        vb = validated_baseline(validated, "national", r.group, sd_floor_logit)
        if vb is not None:
            gaps.append(r.b - vb[0])
    return float(np.sqrt(np.mean(np.square(gaps)))) if gaps else 0.0


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
              min_n: int = 75, validated: pd.DataFrame | None = None, sd_floor_logit: float = 0.10,
              ei_sd_floor: float = 0.0
              ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Race/education cells -> observation table; age cells returned separately for the gradient model.

    base: {'national': ..., 'region': ..., 'state': ...} from baseline_table. group_weights: geography, group, w
    (n_group, used to split 'nonwhite' cells). Returns (cells, age_cells). Cells follow
    z = y - b, Var(z) = (100*2*sqrt(p(1-p)) / sqrt(n/deff))^2 + b_sd^2 ('nonwhite': variance x2).

    The 2024 baseline b is the validated-voter studies' mean when `validated` has a 2024 row for that group and
    geography (b_sd = spread across studies); otherwise the EI baseline. With EI in priors-only fallback the EI
    baseline is just the placeholder prior, so the validated rows are strongly preferred. `b_source` records which.
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
            vb = [validated_baseline(validated, geo, g, sd_floor_logit) for g in NONWHITE]
            w = group_weights[(group_weights.geography == geo) & group_weights.group.isin(NONWHITE)]
            wg = {g: float(w.loc[w.group == g, "w"].sum()) for g in NONWHITE}
            if all(v is not None for v in vb) and sum(wg.values()) > 0:
                ws = np.array([wg[g] for g in NONWHITE])
                nb = pd.DataFrame({"b": [float(np.average([v[0] for v in vb], weights=ws))],
                                   "b_sd": [float(np.sqrt(np.sum((ws / ws.sum()) ** 2 * np.array([v[1] for v in vb]) ** 2)))]})
                src = "validated"
            else:
                nb = nonwhite_baseline(bt[bt.geography == geo], group_weights[group_weights.geography == geo])
                src = "ei"
            if nb.empty:
                continue
            tot = w.w.sum() or 1.0
            for g in NONWHITE:
                share = float(w.loc[w.group == g, "w"].sum() / tot) if tot else 0.25
                rows.append(dict(poll_id=r.poll_id, geography=geo, group=g, y=y, b=nb.b.iloc[0], z=y - nb.b.iloc[0],
                                 var=2 * (samp_var + max(float(nb.b_sd.iloc[0]), ei_sd_floor if src == "ei" else 0.0) ** 2), n_group=r.n_group * share, nonwhite=True,
                                 b_source=src))
            continue
        if r.group_value not in GROUPS:
            continue
        vb = validated_baseline(validated, geo, r.group_value, sd_floor_logit)
        if vb is not None:
            b_, bsd_, src = vb[0], vb[1], "validated"
        else:
            b = bt[(bt.geography == geo) & (bt.group == r.group_value)]
            if b.empty:
                continue
            b_, bsd_, src = float(b.b.iloc[0]), max(float(b.b_sd.iloc[0]), ei_sd_floor), "ei"
        rows.append(dict(poll_id=r.poll_id, geography=geo, group=r.group_value, y=y, b=b_, z=y - b_,
                         var=samp_var + bsd_**2, n_group=r.n_group, nonwhite=False, b_source=src))
    cells = pd.DataFrame(rows, columns=CELL_COLS)
    return cells, pd.DataFrame(age_rows)


AREA_CLASSES = ["urban", "suburban", "rural"]


def harmonize_area(cx: pd.DataFrame, deff: float, min_n: int, validated: pd.DataFrame | None,
                   sd_floor_logit: float = 0.10) -> pd.DataFrame:
    """National urban/suburban/rural crosstab cells -> group, z = y - b (validated-voter 2024 area margin), var.
    Cells without a validated 2024 area baseline are dropped (no EI baseline exists for area type)."""
    rows = []
    for r in cx.itertuples():
        if r.group_value not in AREA_CLASSES or r.n_group < min_n or r.geography != "national":
            continue
        vb = validated_baseline(validated, "national", r.group_value, sd_floor_logit)
        if vb is None:
            continue
        p = r.dside_pct / (r.dside_pct + r.rside_pct)
        samp_var = (100 * 2 * np.sqrt(p * (1 - p)) / np.sqrt(r.n_group / deff)) ** 2
        y = 100.0 * (r.dside_pct - r.rside_pct) / (r.dside_pct + r.rside_pct)
        rows.append(dict(poll_id=r.poll_id, group=r.group_value, y=y, b=vb[0], z=y - vb[0], var=samp_var + vb[1] ** 2,
                         n_group=r.n_group))
    return pd.DataFrame(rows, columns=["poll_id", "group", "y", "b", "z", "var", "n_group"])


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
