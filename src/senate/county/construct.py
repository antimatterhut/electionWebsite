"""County swing construction: raw swing = state swing + group tilt + age term (plan §6.8, §6.10)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..ei.groups import GROUPS
from .calibrate import calibrate

EI_OK = ("ok", "retry")


def omega_groups(n_group: pd.DataFrame, dropoff: dict[str, float], groups: list[str] | None = None) -> pd.DataFrame:
    """Expected 2026 group votes omega_ig = n_ig(2024) * d_g, rescaled so each state keeps its 2024 total.

    n_group: geoid, state_po, group, n_group. The state-level scaler c_s here only fixes the scale; the level of
    2026 turnout T_s^2026 is the Phase 5 turnout model's job and does not affect the county tilt (only shares do).
    Early-vote reweighting (omega_ev) is applied by county/run_county.py from processed/early_vote_weights.parquet.
    """
    g = groups or GROUPS
    d = n_group.copy()
    d["omega"] = d.n_group * d.group.map(dropoff)
    tot24 = d.groupby("state_po").n_group.transform("sum")
    tot26 = d.groupby("state_po").omega.transform("sum")
    d["omega"] = d.omega * tot24 / tot26
    return d.pivot(index="geoid", columns="group", values="omega")[g]


def regional_weights(omega: pd.DataFrame, region: pd.Series) -> pd.DataFrame:
    """omega_bar_rg: each region's average group share of expected votes (rows sum to 1)."""
    r = omega.groupby(region.reindex(omega.index).to_numpy()).sum()
    return r.div(r.sum(axis=1), axis=0)


def ei_elasticity(theta: pd.DataFrame, omega: pd.DataFrame, state_of: pd.Series, kappa: float,
                  clip: tuple[float, float] = (0.25, 4.0)) -> pd.DataFrame:
    """County x group scale e_ig = (v_ig / vbar_{s,g})^kappa, v = theta(1-theta) (logit-uniform-swing sensitivity).

    A group's regional swing delta_{g,r} is multiplied by e_ig, so a group that is lopsided in a county (theta near 0
    or 1) moves less there than where it is split. vbar is the omega-weighted state mean of v for the group, so the
    state-level scale stays near 1. kappa=0 gives all ones (no EI effect); the ratio is clipped to `clip` before
    the power. theta: county x group EI posterior means. Missing theta -> 1.
    """
    th = theta.reindex(index=omega.index, columns=omega.columns)
    v = th * (1.0 - th)
    st = state_of.reindex(omega.index).to_numpy()
    num = (v * omega).groupby(st).sum(min_count=1)
    den = omega.where(v.notna()).groupby(st).sum(min_count=1)
    ref = (num / den).reindex(st).set_axis(omega.index)
    e = (v / ref).clip(*clip) ** kappa
    return e.fillna(1.0)


def county_raw_swing(S_s: float, omega: pd.DataFrame, region: pd.Series, delta: pd.DataFrame,
                     z_age: pd.Series | None = None, beta_age: float = 0.0,
                     max_tilt: float | None = 6.0, urban_term: pd.Series | None = None,
                     overlap_shrink: tuple[float, float] = (1.0, 1.0),
                     ei_scale: pd.DataFrame | None = None) -> pd.DataFrame:
    """s_raw_i = S_s + clip(tilt_i + k_age beta_age z_age_i + k_urban urban_i, +-max_tilt).

    tilt_i = raw_i - sum_j nu_j raw_j with raw_i = sum_g share_ig delta_{g,r(i)}: centered once at the STATE level
    (nu = omega weights), so differences in level between regions of one state are kept (calibrate() fixes the mean).
    omega: county x group expected votes; delta: region x group group-swing means. max_tilt=None means no cap.
    overlap_shrink = (k_age, k_urban) discounts the age/urban terms because crosstab swings are marginal (part of
    "young voters swung left" is already in the race x education mix). The group tilt alone is capped at max_tilt as
    well as the total (cap applied after centering). Counties in a region without a delta row get the state-mean raw
    swing (zero tilt).
    ei_scale (county x group, from ei_elasticity) multiplies each group's delta per county, so EI's county-level
    group vote shares make the group swings county-specific; None = 1.
    """
    cap = np.inf if max_tilt is None else max_tilt
    g = list(omega.columns)
    tot = omega.sum(axis=1).to_numpy()
    share = omega.div(omega.sum(axis=1), axis=0)
    dl = delta.reindex(columns=g)
    dc = dl.reindex(region.reindex(omega.index).to_numpy()).to_numpy()  # county x group, NaN where region missing
    if ei_scale is not None:
        dc = dc * ei_scale.reindex(index=omega.index, columns=g).fillna(1.0).to_numpy()
    raw = (share.to_numpy() * dc).sum(axis=1)
    ok = ~np.isnan(dc).any(axis=1)
    if ok.any():
        nu = tot[ok] / tot[ok].sum()
        mean = float((nu * raw[ok]).sum())
        tilt = np.where(ok, raw - mean, 0.0)
    else:
        tilt = np.zeros(len(omega))
    tilt = np.clip(tilt, -cap, cap)
    age = np.zeros(len(omega)) if z_age is None else (
        overlap_shrink[0] * beta_age * z_age.reindex(omega.index).fillna(0.0).to_numpy())
    urb = np.zeros(len(omega)) if urban_term is None else (
        overlap_shrink[1] * urban_term.reindex(omega.index).fillna(0.0).to_numpy())
    out = pd.DataFrame({"tilt": tilt, "age_term": age, "urban_term": urb}, index=omega.index)
    out["s_raw"] = S_s + np.clip(out.tilt + out.age_term + out.urban_term, -cap, cap)
    return out


def method_label(raw: pd.DataFrame) -> str:
    """group_tilt, plus +age / +urban when those terms are nonzero."""
    m = "group_tilt"
    if raw.age_term.abs().max() > 0:
        m += "+age"
    if "urban_term" in raw and raw.urban_term.abs().max() > 0:
        m += "+urban"
    return m


def build_state(state_po: str, S_s: float, counties: pd.DataFrame, omega: pd.DataFrame, delta: pd.DataFrame | None,
                ei_status: str, z_age: pd.Series | None = None, beta_age: float = 0.0,
                max_tilt: float | None = 6.0, urban_term: pd.Series | None = None,
                overlap_shrink: tuple[float, float] = (1.0, 1.0),
                ei_scale: pd.DataFrame | None = None) -> pd.DataFrame:
    """Calibrated county swings for one state.

    The group tilt needs only the county group mix (omega, from CVAP x relative turnout) and the group swing deltas,
    not EI's theta, so it applies whenever deltas exist, whatever `ei_status` says (kept as an argument for callers).
    counties: index geoid, columns m0, region. Returns geoid, m0, tilt, age_term, urban_term, s_raw, s, lam,
    county_method, m_hat.
    """
    if delta is not None:
        counties = counties.reindex(omega.index)
        raw = county_raw_swing(S_s, omega, counties.region, delta, z_age, beta_age, max_tilt, urban_term,
                               overlap_shrink, ei_scale)
        method = method_label(raw)
    else:
        idx = counties.index
        age = np.zeros(len(idx)) if z_age is None or beta_age == 0 else (
            overlap_shrink[0] * beta_age * z_age.reindex(idx).fillna(0).to_numpy())
        raw = pd.DataFrame({"tilt": 0.0, "age_term": age, "urban_term": 0.0}, index=idx)
        raw["s_raw"] = S_s + raw.age_term
        method = "age_only" if z_age is not None and beta_age != 0 else "uniform"
        omega = omega.reindex(idx)
    w = omega.sum(axis=1).to_numpy()
    m0 = counties.m0.reindex(raw.index).to_numpy()
    s, lam = calibrate(m0, raw.s_raw.to_numpy(), w, S_s)
    out = raw.assign(m0=m0, s=s, lam=lam, county_method=method, state_po=state_po)
    out["m_hat"] = out.m0 + out.s
    out["omega"] = w
    return out.reset_index(names="geoid")
