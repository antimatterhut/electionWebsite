"""Hierarchical R x C ecological inference model for 2024 group vote shares (plan §6.6)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class EIData:
    """Everything the model needs for one fit (a state or a pooled census division)."""
    geoid: np.ndarray            # (I,)
    state: np.ndarray            # (I,) state_po
    vd: np.ndarray               # (I,) Democratic two-party votes
    v: np.ndarray                # (I,) two-party votes
    n: np.ndarray                # (I, G) group voters n_ig
    x: np.ndarray                # (I, J) standardised covariates
    region_idx: np.ndarray       # (I,) int
    regions: list[str]
    mu_prior: np.ndarray         # (G,) prior mean of group D share (probability scale)
    sd_prior: np.ndarray         # (G,) prior SD on the logit scale
    groups: list[str]
    covariates: list[str] = field(default_factory=list)
    state_idx: np.ndarray | None = None  # (I,) int, set when states are pooled
    states: list[str] = field(default_factory=list)
    county_eps: bool = True      # include the county x group effect eps_ig

    @property
    def pooled(self) -> bool:
        return self.state_idx is not None and len(self.states) > 1


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def build_model(d: EIData):
    """PyMC model: logit theta_ig = mu_g + x_i.beta_g + u_{r(i)g} (+ s_{st(i)g}) + eps_ig (non-centred).

    V^D_i ~ Normal(sum_g n_ig theta_ig, phi V_i).
    """
    import pymc as pm

    I, G = d.n.shape
    J = d.x.shape[1]
    R = len(d.regions)
    coords = {"county": d.geoid, "group": d.groups, "cov": d.covariates or [f"x{j}" for j in range(J)],
              "region": d.regions}
    with pm.Model(coords=coords) as m:
        mu = pm.Normal("mu", mu=logit(d.mu_prior), sigma=d.sd_prior, dims="group")
        beta = pm.Normal("beta", 0.0, 0.5, dims=("group", "cov")) if J else None
        tau_u = pm.HalfNormal("tau_u", 0.5)
        tau_e = pm.HalfNormal("tau_e", 0.5) if d.county_eps else None
        u = pm.Normal("u_raw", 0.0, 1.0, dims=("region", "group")) * tau_u
        eta = mu[None, :] + u[d.region_idx]
        if J:
            eta = eta + pm.math.dot(d.x, beta.T)
        if d.pooled:
            tau_s = pm.HalfNormal("tau_s", 0.5)
            s = pm.Normal("s_raw", 0.0, 1.0, shape=(len(d.states), G)) * tau_s
            eta = eta + s[d.state_idx]
        if d.county_eps:
            eta = eta + pm.Normal("eps_raw", 0.0, 1.0, dims=("county", "group")) * tau_e
        theta = pm.Deterministic("theta", pm.math.sigmoid(eta), dims=("county", "group"))
        phi = pm.HalfNormal("phi", 25.0)
        mean = (d.n * theta).sum(axis=1)
        pm.Normal("vd", mu=mean, sigma=pm.math.sqrt(phi * d.v), observed=d.vd, dims="county")
    return m


SCALAR_VARS = ["mu", "tau_u", "tau_e", "phi"]  # tau_e absent when county_eps is off


def sample(d: EIData, chains: int, tune: int, draws: int, target_accept: float, seed: int,
           nuts_sampler: str | None = None, progressbar: bool = False):
    """Sample with the numpyro NUTS backend when available (plan: PyMC with numpyro), else PyMC's own NUTS."""
    import pymc as pm

    if nuts_sampler is None:
        try:
            import numpyro  # noqa: F401
            nuts_sampler = "numpyro"
        except ImportError:
            nuts_sampler = "pymc"
    m = build_model(d)
    kw = {"nuts_sampler_kwargs": {"chain_method": "vectorized"}} if nuts_sampler == "numpyro" else {}
    with m:
        return pm.sample(draws=draws, tune=tune, chains=chains, cores=1 if nuts_sampler == "numpyro" else chains,
                         target_accept=target_accept, random_seed=seed, nuts_sampler=nuts_sampler,
                         progressbar=progressbar, **kw)


def run_pyei_reference(group_fracs: np.ndarray, vote_fracs: np.ndarray, pops: np.ndarray, seed: int = 20260,
                       draws: int = 500, tune: int = 500, chains: int = 2) -> np.ndarray:
    """PyEI RowByColumnEI(model_name='multinomial-dirichlet-modified') reference: R x C posterior-median matrix.

    group_fracs (I, R) group shares per county, vote_fracs (I, C) candidate shares, pops (I,) voters. Returns the
    (R, C) matrix of posterior medians of the group-by-candidate vote fractions. Used by test_ei_reference_agreement
    to check the custom model against the standard implementation (plan §6.6 'Baseline implementation check')."""
    from pyei.r_by_c import RowByColumnEI

    ei = RowByColumnEI(model_name="multinomial-dirichlet-modified")
    ei.fit(np.asarray(group_fracs).T, np.asarray(vote_fracs).T, np.asarray(pops).astype(int), draw_samples=True,
           tune=tune, draws=draws, chains=chains, random_seed=seed)
    return np.median(np.asarray(ei.sampled_voting_prefs), axis=0)


def posterior_summary(idata, d: EIData) -> pd.DataFrame:
    """Per (county, group): theta mean/p10/p90 over all chains and draws."""
    th = idata.posterior["theta"].stack(s=("chain", "draw")).transpose("county", "group", "s").values
    return pd.DataFrame({
        "geoid": np.repeat(d.geoid, len(d.groups)),
        "group": np.tile(d.groups, len(d.geoid)),
        "theta_mean": th.mean(axis=2).ravel(),
        "theta_p10": np.percentile(th, 10, axis=2).ravel(),
        "theta_p90": np.percentile(th, 90, axis=2).ravel(),
    })
