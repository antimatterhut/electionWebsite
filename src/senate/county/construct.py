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


def county_raw_swing(S_s: float, omega: pd.DataFrame, region: pd.Series, delta: pd.DataFrame,
                     reg_w: pd.DataFrame, z_age: pd.Series | None = None, beta_age: float = 0.0,
                     max_tilt: float = 6.0) -> pd.DataFrame:
    """s_raw_i = S_s + sum_g w_ig (delta_{g,r(i)} - dbar_r(i)) + beta_age z_age_i; |tilt| capped at max_tilt.

    omega: county x group expected votes; delta: region x group group-swing means; reg_w: region x group weights.
    Counties in a region without a delta row get delta equal to the regional mean (zero tilt).
    """
    g = list(omega.columns)
    share = omega.div(omega.sum(axis=1), axis=0)
    reg = region.reindex(omega.index)
    dl = delta.reindex(columns=g)
    dbar = (reg_w.reindex(columns=g).reindex(dl.index) * dl).sum(axis=1)
    dev = dl.sub(dbar, axis=0)  # region x group, mean-zero at regional weights
    dev_c = dev.reindex(reg.to_numpy()).to_numpy()  # county x group, NaN where region missing
    dev_c = np.nan_to_num(dev_c, nan=0.0)
    tilt = (share.to_numpy() * dev_c).sum(axis=1)
    tilt = np.clip(tilt, -max_tilt, max_tilt)
    age = np.zeros(len(omega)) if z_age is None else beta_age * z_age.reindex(omega.index).fillna(0.0).to_numpy()
    out = pd.DataFrame({"tilt": tilt, "age_term": age}, index=omega.index)
    out["s_raw"] = S_s + out.tilt + out.age_term
    return out


def build_state(state_po: str, S_s: float, counties: pd.DataFrame, omega: pd.DataFrame, delta: pd.DataFrame | None,
                reg_w: pd.DataFrame | None, ei_status: str, z_age: pd.Series | None = None, beta_age: float = 0.0,
                max_tilt: float = 6.0) -> pd.DataFrame:
    """Calibrated county swings for one state.

    counties: index geoid, columns m0, region. Returns geoid, m0, tilt, age_term, s_raw, s, lam, county_method, m_hat.
    """
    counties = counties.reindex(omega.index) if delta is not None and ei_status in EI_OK else counties
    if delta is not None and reg_w is not None and ei_status in EI_OK:
        raw = county_raw_swing(S_s, omega, counties.region, delta, reg_w, z_age, beta_age, max_tilt)
        method = "ei_crosstab"
    else:
        idx = counties.index
        age = np.zeros(len(idx)) if z_age is None or beta_age == 0 else beta_age * z_age.reindex(idx).fillna(0).to_numpy()
        raw = pd.DataFrame({"tilt": 0.0, "age_term": age}, index=idx)
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
