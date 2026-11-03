"""Correlation structure of the simulation error terms (plan §6.12 table)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..ei.groups import GROUPS, REGIONS

# Region adjacency (the plan only says "neighbours"; this is the documented choice). Black Belt / Rio Grande are
# county carve-outs of the South / Mountain-Southwest and touch their parents.
REGION_NEIGHBORS = [("northeast", "midwest"), ("northeast", "south"), ("midwest", "south"), ("midwest", "mountain"),
                    ("south", "black_belt"), ("south", "rio_grande"), ("mountain", "rio_grande"),
                    ("mountain", "pacific")]
GROUP_CORR = {("black", "hispanic"): 0.3, ("wnh_college", "wnh_noncollege"): -0.3}
SAME_STATE_RHO = 0.7  # two contests in one state (regular + special): shared state-level error; assumption, backtests only


def nearest_psd(c: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    """Clip negative eigenvalues and rescale to a unit diagonal."""
    c = (c + c.T) / 2
    w, v = np.linalg.eigh(c)
    out = (v * np.clip(w, eps, None)) @ v.T
    d = np.sqrt(np.diag(out))
    return out / np.outer(d, d)


def region_corr(rho: float, regions: list[str] | None = None) -> np.ndarray:
    regs = regions or REGIONS
    c = np.eye(len(regs))
    for a, b in REGION_NEIGHBORS:
        if a in regs and b in regs:
            i, j = regs.index(a), regs.index(b)
            c[i, j] = c[j, i] = rho
    return nearest_psd(c)


def group_corr(groups: list[str] | None = None) -> np.ndarray:
    g = groups or GROUPS
    c = np.eye(len(g))
    for (a, b), v in GROUP_CORR.items():
        c[g.index(a), g.index(b)] = c[g.index(b), g.index(a)] = v
    return nearest_psd(c)


def cosine_similarity(comp: pd.DataFrame) -> pd.DataFrame:
    """Pairwise cosine similarity (>= 0) of state CVAP composition rows; diagonal set to 1."""
    x = comp.to_numpy(float)
    x = x / np.linalg.norm(x, axis=1, keepdims=True).clip(1e-12)
    s = np.clip(x @ x.T, 0.0, 1.0)
    np.fill_diagonal(s, 1.0)
    return pd.DataFrame(s, index=comp.index, columns=comp.index)


def state_correlation(sim: pd.DataFrame, rho_state: float, contest_state: list[str] | None = None) -> np.ndarray:
    """Corr(e_s, e_s') = rho * sim(s,s') off the diagonal (plan: Cov = sigma^2 (delta + rho sim)); forced PSD.

    contest_state: state of each contest; contests sharing a state get SAME_STATE_RHO."""
    c = rho_state * sim.to_numpy(float)
    np.fill_diagonal(c, 1.0)
    if contest_state is not None:
        cs = np.asarray(contest_state)
        same = (cs[:, None] == cs[None, :]) & ~np.eye(len(cs), dtype=bool)
        c[same] = SAME_STATE_RHO
    return nearest_psd(c)


def state_covariance(sd: np.ndarray, corr: np.ndarray) -> np.ndarray:
    return corr * np.outer(sd, sd)


def state_composition(cvap: pd.DataFrame, state_of: pd.Series) -> pd.DataFrame:
    """State x race5 CVAP shares from the county CVAP table (geoid, race5, cvap)."""
    st = cvap.assign(state_po=cvap.geoid.map(state_of)).dropna(subset=["state_po"])
    w = st.pivot_table(index="state_po", columns="race5", values="cvap", aggfunc="sum", fill_value=0.0)
    return w.div(w.sum(axis=1), axis=0)
