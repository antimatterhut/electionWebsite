"""Custom hierarchical EI vs PyEI reference and the identification test (plan §6.6, §11.2)."""
from __future__ import annotations

import numpy as np
import pytest

from senate.ei.model_rxc import EIData, logit, posterior_summary, run_pyei_reference, sample

pytest.importorskip("pymc")
pytest.importorskip("numpyro")

GROUPS3 = ["a", "b", "c"]
TRUTH = np.array([0.35, 0.88, 0.55])  # known group D shares
PRIOR = np.array([0.40, 0.80, 0.50])  # deliberately a bit off, sd wide enough to be corrected by data


def _synthetic(shares: np.ndarray, seed: int = 3) -> EIData:
    r = np.random.default_rng(seed)
    I = len(shares)
    v = r.integers(8_000, 60_000, I).astype(float)
    n = shares * v[:, None]
    th = 1 / (1 + np.exp(-(logit(TRUTH)[None, :] + r.normal(0, 0.15, (I, 3)))))
    vd = (n * th).sum(axis=1) + r.normal(0, 50, I)
    return EIData(np.array([f"{i:05d}" for i in range(I)]), np.array(["XX"] * I), vd, v, n, np.zeros((I, 0)),
                  np.zeros(I, int), ["south"], PRIOR, np.full(3, 0.6), GROUPS3)


def _group_means(d: EIData, idata) -> np.ndarray:
    s = posterior_summary(idata, d)
    return s.groupby("group").apply(lambda x: np.average(x.theta_mean, weights=d.n[:, GROUPS3.index(x.name)]),
                                    include_groups=False).reindex(GROUPS3).to_numpy()


def test_ei_reference_agreement_heterogeneous():
    """Heterogeneous counties: custom model recovers known shares within 3 pts and agrees with PyEI within 5."""
    r = np.random.default_rng(11)
    shares = r.dirichlet([0.6, 0.6, 0.6], size=60)
    d = _synthetic(shares)
    idata = sample(d, chains=2, tune=500, draws=500, target_accept=0.92, seed=20260)
    est = _group_means(d, idata)
    assert np.abs(est - TRUTH).max() < 0.03

    big = shares.mean(axis=0) >= 0.10
    vote_fracs = np.column_stack([d.vd / d.v, 1 - d.vd / d.v])
    ref = run_pyei_reference(shares, vote_fracs, d.v, draws=400, tune=400, chains=2)
    ref_d = ref[:, 0]
    assert np.abs(est[big] - ref_d[big]).max() < 0.05


def test_ei_identification_homogeneous_counties_degrade_gracefully():
    """Near-identical county compositions carry no group information: the posterior stays prior-wide (or the
    diagnostics fail so the run is marked retry/fallback); it must not report confident, wrong group shares."""
    r = np.random.default_rng(5)
    shares = np.tile([0.5, 0.3, 0.2], (60, 1)) + r.normal(0, 0.002, (60, 3))
    shares = shares / shares.sum(axis=1, keepdims=True)
    d = _synthetic(shares)
    idata = sample(d, chains=2, tune=500, draws=500, target_accept=0.92, seed=20260)
    s = posterior_summary(idata, d)
    width = (s.theta_p90 - s.theta_p10).groupby(s.group).mean()
    prior_width = (1 / (1 + np.exp(-(logit(PRIOR) + 1.2816 * 0.6))) - 1 / (1 + np.exp(-(logit(PRIOR) - 1.2816 * 0.6))))
    # at least one group posterior stays wide (>= 40% of the prior interval) - nothing sharper is identified
    assert (width.reindex(GROUPS3).to_numpy() >= 0.4 * prior_width).any()
