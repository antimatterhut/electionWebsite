"""MCMC diagnostics and the retry / fallback decision (plan §6.6 sampler settings)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Diag:
    rhat_max: float
    ess_bulk_min: float
    ess_tail_min: float
    divergences: int
    bfmi_min: float

    def passes(self, rhat_max: float = 1.01, ess_min: float = 400.0, bfmi_min: float = 0.3) -> bool:
        return bool(self.rhat_max < rhat_max and self.ess_bulk_min > ess_min and self.ess_tail_min > ess_min
                    and self.divergences == 0 and self.bfmi_min > bfmi_min)

    def as_dict(self) -> dict:
        return {k: float(v) for k, v in self.__dict__.items()}


def _flat(ds) -> np.ndarray:
    return np.concatenate([np.asarray(ds[v]).reshape(-1) for v in ds.data_vars])


def diagnose(idata, var_names: list[str] | None = None) -> Diag:
    """Summarise convergence for an InferenceData (posterior + sample_stats)."""
    import arviz as az

    post = idata.posterior.to_dataset()
    names = [v for v in (var_names or list(post.data_vars)) if v in post.data_vars]
    sub = post[names]
    rhat = _flat(az.rhat(sub))
    ess_b = _flat(az.ess(sub, method="bulk"))
    ess_t = _flat(az.ess(sub, method="tail"))
    ss = idata.sample_stats.to_dataset()
    div = int(np.asarray(ss["diverging"]).sum()) if "diverging" in ss else 0
    try:
        bfmi = float(np.min(np.asarray(az.bfmi(idata))))
    except Exception:  # noqa: BLE001 - numpyro stats may lack the energy field
        bfmi = float("nan")
    return Diag(float(np.nanmax(rhat)), float(np.nanmin(ess_b)), float(np.nanmin(ess_t)), div,
                1.0 if np.isnan(bfmi) else bfmi)
