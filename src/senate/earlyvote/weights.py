"""Early-vote category multipliers -> county turnout weights, with the +/-cap_pts bisection (plan §6.9)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..ei.groups import GROUPS

RACE_GROUPS = {"white": ["wnh_college", "wnh_noncollege"], "black": ["black"], "hispanic": ["hispanic"],
               "asian": ["asian"], "other": ["other"]}
PARTIES = ["D", "R", "O", "U"]


def party_to_group_matrix(comp: pd.DataFrame, groups: list[str] | None = None) -> pd.DataFrame:
    """Q[p, g] = share of group g's voters registered with party p (columns sum to 1).

    comp: state voter-file composition (or 2024 exit / validated-voter data) with columns group, party, count.
    Groups with no rows get the all-group party mix."""
    g = groups or GROUPS
    c = comp.pivot_table(index="party", columns="group", values="count", aggfunc="sum").reindex(index=PARTIES).fillna(0.0)
    if c.values.sum() <= 0:
        raise ValueError("empty party-by-group composition")
    mix = c.sum(axis=1) / c.values.sum()
    q = c.reindex(columns=g).div(c.reindex(columns=g).sum(axis=0).replace(0, np.nan), axis=1)
    for col in g:
        if q[col].isna().any():
            q[col] = mix
    return q


def base_by_category(dim: str | None, cats: list[str], n_group: pd.Series, q: pd.DataFrame | None = None,
                     age_base: pd.Series | None = None) -> pd.Series:
    """Baseline (no-EV) 2026 ballots by category, from baseline group voters n_group (state sums of omega_base)."""
    if dim == "party":
        return pd.Series({p: float((q.loc[p] * n_group.reindex(q.columns)).sum()) for p in cats})
    if dim == "race5":
        return pd.Series({r: float(n_group.reindex(RACE_GROUPS[r]).sum()) for r in cats})
    if dim == "age_bin":
        return age_base.reindex(cats) * float(n_group.sum())
    return pd.Series({"total": float(n_group.sum())})


def category_psi(final_hat: pd.Series, final_base: pd.Series) -> pd.Series:
    """psi_j = (Final_hat_j / Final_base_j) / (Final_hat_tot / Final_base_tot) over the common categories."""
    idx = final_hat.index.intersection(final_base.index)
    fh, fb = final_hat[idx], final_base[idx]
    return (fh / fh.sum()) / (fb / fb.sum())


def shrink(psi: pd.Series, gamma: float) -> pd.Series:
    """psi^shr = exp(gamma * log psi)."""
    return np.exp(gamma * np.log(psi))


def group_factors(dim: str | None, psi_shr: pd.Series | None, q: pd.DataFrame | None, groups: list[str]) -> pd.Series:
    """Per-EI-group multiplier. Party goes through Q (psi_g = sum_p Q[p,g] psi_p); race maps directly;
    age is county-level (see EVModel) so groups stay at 1."""
    f = pd.Series(1.0, index=groups)
    if psi_shr is None:
        return f
    if dim == "party":
        return (q.reindex(columns=groups).mul(psi_shr.reindex(q.index).fillna(1.0), axis=0)).sum(axis=0)
    if dim == "race5":
        for r, gs in RACE_GROUPS.items():
            if r in psi_shr.index:
                f[gs] = psi_shr[r]
    return f


def county_blend(ev_now: pd.Series, ev_hist: pd.Series) -> pd.Series:
    """EV_i^2026 / EV_i^hist where both are positive (NaN elsewhere -> treated as 1)."""
    h = ev_hist.reindex(ev_now.index)
    return (ev_now / h).where((h > 0) & (ev_now >= 0))


@dataclass
class EVModel:
    """One state's early-vote reweighting. n_ig is the baseline county x group weight table (omega_base)."""
    n_ig: pd.DataFrame
    m0: pd.Series
    dim: str | None = None
    psi: pd.Series | None = None            # raw category multipliers (before shrink)
    q: pd.DataFrame | None = None
    age_share: pd.DataFrame | None = None   # county x age_bin share of voters
    blend: pd.Series | None = None          # county EV ratio
    gamma: float = 0.5
    kappa_county: float = 0.25

    def omega(self, scale: float = 1.0) -> pd.DataFrame:
        """omega^EV(scale): group/age multipliers at exponent gamma*scale, county blend at kappa_county*scale,
        renormalised to the baseline state total."""
        g = self.gamma * scale
        psi_shr = shrink(self.psi, g) if self.psi is not None and len(self.psi) else None
        w = self.n_ig * group_factors(self.dim, psi_shr, self.q, list(self.n_ig.columns))
        if self.dim == "age_bin" and psi_shr is not None and self.age_share is not None:
            a = (self.age_share.reindex(self.n_ig.index).fillna(0.0) * psi_shr.reindex(self.age_share.columns).fillna(1.0)).sum(axis=1)
            w = w.mul(a.where(a > 0, 1.0), axis=0)
        if self.blend is not None:
            b = self.blend.reindex(self.n_ig.index).fillna(1.0).clip(lower=1e-6) ** (self.kappa_county * scale)
            w = w.mul(b, axis=0)
        return w * (self.n_ig.values.sum() / w.values.sum())

    def margin(self, omega: pd.DataFrame) -> float:
        """m0_s(omega) = sum_i nu_i m0_i."""
        w = omega.sum(axis=1)
        return float((w * self.m0.reindex(w.index)).sum() / w.sum())


def apply_cap(model: EVModel, cap: float, tol: float = 1e-12) -> dict:
    """E_s = m0_s(omega^EV) - m0_s(omega^base), enforcing |E_s| <= cap by scaling gamma -> gamma*kappa, kappa in (0,1]
    (county blend exponent scaled too, so county-only states are capped as well). Bisection on |E(kappa)| - cap."""
    base = model.margin(model.n_ig)
    e = lambda k: model.margin(model.omega(k)) - base  # noqa: E731
    e_raw = e(1.0)
    kappa, binding = 1.0, abs(e_raw) > cap
    if binding:
        lo, hi = 0.0, 1.0  # |E(0)| = 0 < cap < |E(1)|: a root exists by continuity
        for _ in range(200):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if abs(e(mid)) < cap else (lo, mid)
            if hi - lo < tol:
                break
        kappa = lo  # the side with |E| < cap, so the cap is never exceeded
    om = model.omega(kappa)
    return {"omega": om, "E_raw": e_raw, "E": model.margin(om) - base, "kappa": kappa, "cap_binding": binding}
