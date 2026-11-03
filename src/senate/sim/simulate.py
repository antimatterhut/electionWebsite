"""Monte Carlo simulation of the county and state margins (plan §6.12).

M_i = m_hat_i + e_nat + e_reg[r(i)] + sum_g wbar_sg e_grp_g + e_state_s + e_cty_i

The state margin is the nu-weighted county margin, so the county term (demeaned with nu weights inside each state)
never moves a state total. Without a county layer the same draws are made at state level with the region shock
entering through the state's region shares. Student-t terms use the exact scale mixture t = z / sqrt(W/df), rescaled
to unit variance, so every sigma in `ErrorModel` is a standard deviation.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..ei.groups import GROUPS, REGIONS
from . import covariance as C
from .errors import ErrorModel

Q = 10.0  # int8 quantisation: 0.1-pt resolution
INT8_MAX = 127


@dataclass
class SimInputs:
    units: pd.DataFrame          # index = contest key; m_hat, sd_state, state_po
    region_share: pd.DataFrame   # unit x REGIONS, rows sum to 1
    group_w: pd.DataFrame        # unit x GROUPS, rows sum to 1
    corr_state: np.ndarray       # unit x unit correlation of e_state
    counties: pd.DataFrame | None = None  # geoid, unit, region, m_hat, nu (share of unit's votes), votes


@dataclass
class SimResult:
    units: list[str]
    margins: np.ndarray                  # n_draws x units, float32 margin (D-side minus R)
    m_hat: np.ndarray
    county_ids: list[str] | None = None
    county_dev: np.ndarray | None = None  # n_draws x counties, int8: round(10 * (M_i - m_hat_i)), saturating at +-12.7
    county_m_hat: np.ndarray | None = None
    e_nat: np.ndarray | None = None


def state_sd(polled: pd.Series, n_eff: pd.Series, em: ErrorModel, sigma_poll: float) -> np.ndarray:
    """sigma_state,s: polled -> sqrt(sd^2 + SE_avg^2), unpolled -> sqrt(sd^2 + extra^2) (plan §6.12)."""
    se2 = sigma_poll**2 / n_eff.clip(lower=1.0)
    extra = np.where(polled.astype(bool), se2, em.state_unpolled_extra**2)
    return np.sqrt(em.state**2 + extra)


def _tscale(rng: np.random.Generator, n: int, df: float) -> np.ndarray:
    """sqrt((df-2)/W), W ~ chi2(df): multiply a standard normal to get a unit-variance Student t."""
    return np.sqrt((df - 2.0) / rng.chisquare(df, n))


def draw_shared(inp: SimInputs, em: ErrorModel, region_rho: float, n: int, rng: np.random.Generator) -> dict:
    """All state-level and shared terms for n draws (n even, antithetic pairs on e_nat)."""
    if n % 2:
        raise ValueError("n_draws must be even (antithetic pairs)")
    df = em.t_df
    half = rng.standard_normal(n // 2)
    sc = _tscale(rng, n // 2, df)
    e_nat = em.national * np.concatenate([half * sc, -half * sc])
    L_reg = np.linalg.cholesky(C.region_corr(region_rho))
    e_reg = em.region * (rng.standard_normal((n, len(REGIONS))) @ L_reg.T) * _tscale(rng, n, df)[:, None]
    L_grp = np.linalg.cholesky(C.group_corr())
    e_grp = em.group * (rng.standard_normal((n, len(GROUPS))) @ L_grp.T)
    L_st = np.linalg.cholesky(inp.corr_state + 1e-10 * np.eye(len(inp.corr_state)))
    sd = inp.units.sd_state.to_numpy(float)
    e_state = (rng.standard_normal((n, len(sd))) @ L_st.T) * sd * _tscale(rng, n, df)[:, None]
    e_group_u = e_grp @ inp.group_w[GROUPS].to_numpy(float).T
    e_reg_u = e_reg @ inp.region_share[REGIONS].to_numpy(float).T
    return {"e_nat": e_nat, "e_reg": e_reg, "e_grp": e_grp, "e_state": e_state, "e_group_u": e_group_u,
            "e_reg_u": e_reg_u}


def simulate(inp: SimInputs, em: ErrorModel, n_draws: int, seed: int, region_rho: float = 0.3,
             chunk: int = 2000) -> SimResult:
    rng = np.random.default_rng(seed)
    n = n_draws + (n_draws % 2)
    sh = draw_shared(inp, em, region_rho, n, rng)
    m_hat = inp.units.m_hat.to_numpy(float)
    margins = (m_hat[None, :] + sh["e_nat"][:, None] + sh["e_reg_u"] + sh["e_group_u"] + sh["e_state"]).astype(np.float32)
    res = SimResult(list(inp.units.index), margins, m_hat, e_nat=sh["e_nat"])
    cty = inp.counties
    if cty is None or not len(cty):
        return res
    unit_idx = inp.units.index.get_indexer(cty.unit)
    reg_idx = np.array([REGIONS.index(r) for r in cty.region])
    nu = cty.nu.to_numpy(float)
    votes = cty.votes.to_numpy(float)
    scale = em.county * np.maximum(0.5, 1.0 / np.sqrt(np.maximum(votes, 1.0) / 1e4))
    agg = np.zeros((len(cty), len(inp.units)))
    agg[np.arange(len(cty)), unit_idx] = nu  # unit mean of a county term = e @ agg
    dev = np.empty((n, len(cty)), dtype=np.int8)
    for lo in range(0, n, chunk):
        hi = min(lo + chunk, n)
        e = rng.standard_normal((hi - lo, len(cty))) * scale
        e -= (e @ agg)[:, unit_idx]  # nu-weighted demean within unit: zero-sum
        d = (sh["e_nat"][lo:hi, None] + sh["e_reg"][lo:hi][:, reg_idx] + sh["e_group_u"][lo:hi][:, unit_idx]
             + sh["e_state"][lo:hi][:, unit_idx] + e)
        dev[lo:hi] = np.clip(np.rint(d * Q), -INT8_MAX, INT8_MAX).astype(np.int8)
    res.county_ids, res.county_dev, res.county_m_hat = list(cty.geoid), dev, cty.m_hat.to_numpy(float)
    return res


def region_shares(units: pd.Index, counties: pd.DataFrame | None, unit_region: pd.Series | None = None) -> pd.DataFrame:
    """unit x REGIONS shares: from county nu weights if present, else one-hot on the unit's (coarse) region."""
    out = pd.DataFrame(0.0, index=units, columns=REGIONS)
    if counties is not None and len(counties):
        s = counties.groupby(["unit", "region"]).nu.sum().unstack(fill_value=0.0)
        out.loc[s.index, s.columns] = s
    else:
        for u in units:
            out.loc[u, unit_region[u]] = 1.0
    return out
