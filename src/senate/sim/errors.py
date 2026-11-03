"""Simulation error magnitudes (plan §6.12): config defaults and the REML fit from historical midterm polling misses.

miss_{s,y} = u_y + v_{reg(s),y} + w_s + eta_{sy}, fitted with statsmodels MixedLM (crossed variance components):
sigma_nat = sd(u), sigma_reg = sd(v), sigma_state = sqrt(var(w) + var(eta)). The county term is fitted separately from
county backtest residuals (`county_sd_from_residuals`). With too few rows the config defaults are used and say so."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
import structlog

from ..config import Settings
from ..ei.groups import _STATE_REGION

log = structlog.get_logger()
MIN_ROWS = 30
MIN_YEARS = 4
SD_FLOOR_FRAC = 0.5  # fitted sigma never goes below half its default (plan §14: floors on sigma)
FACTOR = 1.5  # plan §6.12 acceptance: fitted within a factor of 1.5 of the default
TERMS = ("national", "region", "state", "county", "group")


@dataclass
class ErrorModel:
    national: float
    region: float
    state: float
    group: float
    county: float
    state_unpolled_extra: float
    t_df: float
    source: str = "config_default"
    n_rows: int = 0
    notes: list[str] = field(default_factory=list)
    comparison: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def default_error_model(cfg: Settings) -> ErrorModel:
    sd = cfg.sim.sd
    return ErrorModel(sd.national, sd.region, sd.state, sd.group, sd.county, sd.state_unpolled_extra, cfg.sim.t_df)


def region_of(state_po: str) -> str:
    return _STATE_REGION.get(state_po, "midwest")


def _compare(fitted: dict, default: ErrorModel) -> dict:
    out = {}
    for k, v in fitted.items():
        d = getattr(default, k)
        out[k] = {"default": d, "fitted": v, "ratio": v / d, "within_factor_1.5": (1 / FACTOR) <= v / d <= FACTOR}
    return out


def fit_error_model(misses: pd.DataFrame, cfg: Settings, exclude_year: int | None = None,
                    generic: pd.DataFrame | None = None) -> ErrorModel:
    """misses: year, state_po, race, poll_avg_margin, actual_margin, n_polls (D-minus-R pts).

    exclude_year drops a cycle (used by backtests so a cycle never informs its own error model).
    generic: optional year, gb_margin, house_margin rows; blends the national sd with the generic-ballot miss."""
    default = default_error_model(cfg)
    d = misses.dropna(subset=["poll_avg_margin", "actual_margin"]).copy() if len(misses) else misses
    if exclude_year is not None and len(d):
        d = d[d.year != exclude_year]
    if len(d) < MIN_ROWS or (len(d) and d.year.nunique() < MIN_YEARS):
        default.notes.append(f"config defaults: {len(d)} usable historical misses over "
                             f"{d.year.nunique() if len(d) else 0} cycles (need >= {MIN_ROWS} over >= {MIN_YEARS})")
        default.n_rows = len(d)
        return default
    import statsmodels.formula.api as smf

    d["miss"] = d.actual_margin - d.poll_avg_margin
    d["reg"] = d.state_po.map(region_of)
    d["reg_year"] = d.reg + "_" + d.year.astype(str)
    d["one"] = 1
    try:
        md = smf.mixedlm("miss ~ 1", d, groups="one", re_formula="0",
                         vc_formula={"year": "0 + C(year)", "reg": "0 + C(reg_year)", "state": "0 + C(state_po)"})
        res = md.fit(reml=True, method="lbfgs")
        vc = dict(zip(md.exog_vc.names, np.asarray(res.vcomp)))
        scale = float(res.scale)
    except Exception as e:  # noqa: BLE001 - singular fits are common with few cycles; fall back loudly
        default.notes.append(f"config defaults: REML fit failed ({type(e).__name__}: {str(e)[:120]})")
        default.n_rows = len(d)
        return default
    s_nat = float(np.sqrt(max(vc.get("year", 0.0), 0.0)))
    s_reg = float(np.sqrt(max(vc.get("reg", 0.0), 0.0)))
    s_state = float(np.sqrt(max(vc.get("state", 0.0), 0.0) + max(scale, 0.0)))
    notes = []
    if generic is not None and len(generic) >= 4:
        gb = generic if exclude_year is None else generic[generic.year != exclude_year]
        if len(gb) >= 4:
            s_gb = float(np.sqrt(np.mean((gb.house_margin - gb.gb_margin) ** 2)))
            s_nat = float(np.sqrt((s_nat**2 + s_gb**2) / 2))
            notes.append(f"national sd blends Senate-year effect with generic-ballot miss ({len(gb)} cycles)")
    fitted = {"national": s_nat, "region": s_reg, "state": s_state}
    comparison = _compare(fitted, default)
    floored = {k: max(v, SD_FLOOR_FRAC * getattr(default, k)) for k, v in fitted.items()}
    for k in fitted:
        if floored[k] != fitted[k]:
            notes.append(f"{k} sd floored at {SD_FLOOR_FRAC:.0%} of default")
    out = ErrorModel(floored["national"], floored["region"], floored["state"], default.group, default.county,
                     default.state_unpolled_extra, default.t_df, "fitted_reml", len(d), notes, comparison)
    bad = [k for k, c in comparison.items() if not c["within_factor_1.5"]]
    if bad:
        out.notes.append(f"fitted sd outside a factor of {FACTOR} of default for {bad}: document before launch")
    return out


def county_sd_from_residuals(resid: pd.DataFrame, default: float) -> tuple[float, str]:
    """sigma_cty from county backtest residuals: resid has state_po, error (m_hat - actual) and weight. The
    state-level error is removed with a weighted state demean, matching the zero-sum county term in the simulation."""
    if resid is None or len(resid) < 100:
        return default, "config_default"
    w = resid.weight.astype(float)
    mean = (resid.error * w).groupby(resid.state_po).transform("sum") / w.groupby(resid.state_po).transform("sum")
    dev = resid.error - mean
    # scale away the votes-dependent factor used in the simulation so sigma_cty is comparable to the default
    scale = np.maximum(0.5, 1.0 / np.sqrt(np.maximum(w, 1.0) / 1e4))
    return float(np.sqrt(np.mean((dev / scale) ** 2))), "county_backtest_residuals"
