"""Hierarchical shrinkage of crosstab group swings toward the overall swing (plan §6.7)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Settings

TAU_PRIOR_SD = 3.0  # HalfNormal(3.0) on tau_a, tau_b
PRIOR_E_TAU2 = TAU_PRIOR_SD**2  # E[tau^2] of a HalfNormal(sigma) is sigma^2


def cell_weights(cells: pd.DataFrame, region_weights: pd.DataFrame, regions: list[str],
                 geo_region: dict[str, dict[str, float]]) -> np.ndarray:
    """Cell x region matrix: which regions' delta_{g,r} a poll cell's swing averages over.

    A region-level cell maps to its region; a state cell to that state's vote-weighted regions; a national cell to
    all regions at group g's regional weights (region_weights: region x group). Rows sum to 1."""
    W = np.zeros((len(cells), len(regions)))
    ri = {r: i for i, r in enumerate(regions)}
    for k, c in enumerate(cells.itertuples()):
        if c.geography in ri:
            W[k, ri[c.geography]] = 1.0
        elif c.geography in geo_region:
            for r, w in geo_region[c.geography].items():
                W[k, ri[r]] = w
        else:  # national
            col = region_weights[c.group].reindex(regions).fillna(0.0).to_numpy()
            W[k] = col / col.sum() if col.sum() > 0 else 1.0 / len(regions)
    return W


def prior_only(groups: list[str], regions: list[str], pattern_g: pd.Series, s_ref: float, lam: float) -> pd.DataFrame:
    """No usable crosstab cells: delta = S_ref + lambda * pattern_g, prior SD, shrinkage 1 (plan §6.8 fallback)."""
    sd = float(np.sqrt(2 * PRIOR_E_TAU2))
    rows = [{"region": r, "group": g, "delta_mean": s_ref + lam * float(pattern_g.get(g, 0.0)), "delta_sd": sd,
             "n_polls": 0, "shrinkage_factor": 1.0} for r in regions for g in groups]
    return pd.DataFrame(rows)


def fit_group_swings(cells: pd.DataFrame, groups: list[str], regions: list[str], pattern_g: pd.Series, s_ref: float,
                     W: np.ndarray, cfg: Settings, state_offset: np.ndarray | None = None) -> pd.DataFrame:
    """z_k ~ N(sum_r W_kr delta_{g(k),r}, v_k); delta_{g,r} = S_ref + a_g + b_{g,r};
    a_g ~ N(lambda p_g, tau_a^2), b_{g,r} ~ N(0, tau_b^2), tau ~ HalfNormal(3).

    cells: group, z, var (+poll_id). state_offset (cells,) converts state-poll cells to the national S_ref scale
    (S_s - S_nat). Returns region, group, delta_mean, delta_sd, n_polls, shrinkage_factor (= posterior / prior var).
    """
    import pymc as pm

    lam = cfg.ei.pattern_persistence
    if cells.empty:
        return prior_only(groups, regions, pattern_g, s_ref, lam)
    gi = cells.group.map({g: i for i, g in enumerate(groups)}).to_numpy()
    z = cells.z.to_numpy(float) - (0.0 if state_offset is None else state_offset)
    v = cells["var"].to_numpy(float)
    G, R = len(groups), len(regions)
    pm_mean = np.array([lam * float(pattern_g.get(g, 0.0)) for g in groups])
    s = cfg.crosstab.sampler
    with pm.Model(coords={"group": groups, "region": regions}):
        tau_a = pm.HalfNormal("tau_a", TAU_PRIOR_SD)
        tau_b = pm.HalfNormal("tau_b", TAU_PRIOR_SD)
        a = pm.Normal("a", pm_mean, tau_a, shape=G)
        b = pm.Normal("b", 0.0, tau_b, shape=(G, R))
        delta = pm.Deterministic("delta", s_ref + a[:, None] + b, dims=("group", "region"))
        mean = (delta[gi] * W).sum(axis=1)
        pm.Normal("z", mean, np.sqrt(v), observed=z)
        idata = pm.sample(draws=s.draws, tune=s.tune, chains=s.chains, target_accept=s.target_accept,
                          random_seed=cfg.ei.sampler.seed, progressbar=False, cores=1)
    d = idata.posterior["delta"].stack(s=("chain", "draw")).transpose("group", "region", "s").values
    prior_var = 2 * PRIOR_E_TAU2  # prior Var(delta_{g,r}) = E[tau_a^2] + E[tau_b^2] with tau ~ HalfNormal(3)
    npolls = cells.groupby("group").poll_id.nunique()
    rows = []
    for gj, g in enumerate(groups):
        for ri, r in enumerate(regions):
            rows.append({"region": r, "group": g, "delta_mean": float(d[gj, ri].mean()),
                         "delta_sd": float(d[gj, ri].std(ddof=1)), "n_polls": int(npolls.get(g, 0)),
                         "shrinkage_factor": float(d[gj, ri].var(ddof=1) / prior_var)})
    return pd.DataFrame(rows)


def analytic_posterior(z: np.ndarray, v: np.ndarray, prior_mean: float, tau2: float, s_ref: float
                       ) -> tuple[float, float]:
    """Closed form for one group with a single shared delta: precision-weighted mean and variance (used by
    test_group_shrinkage_toward_overall): tiny n -> huge v -> posterior = S_ref + prior_mean."""
    prec = 1.0 / tau2 + np.sum(1.0 / v)
    mean = (prior_mean / tau2 + np.sum(z / v)) / prec
    return s_ref + mean, 1.0 / prec
