"""Phase 2 state-level model: polls -> national swing -> 2:1 state swing -> projected margin (plan §6.1-6.5)."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ..config import Settings
from ..polls.average import run_poll_averages
from . import combine, national, state as state_mod


def run_state_model(generic: pd.DataFrame, senate: pd.DataFrame, baselines: pd.DataFrame, npv_margin: float,
                    as_of: date, cfg: Settings, ratings: dict[str, float] | None = None,
                    contests: dict[str, str] | None = None, rcv_states: set[str] | None = None,
                    weights: tuple[float, float] | None = None, gb_override: float | None = None,
                    incumbent_sign: dict[str, int] | None = None, demo_dev: dict[str, float] | None = None) -> dict:
    """Returns {"national": {...}, "states": DataFrame, "polling": PollingResult}.

    baselines: state_po, m0. contests: {contest key -> state_po} (default: each race keyed by its state; specials
    use e.g. 'MN-S'). gb_override replaces the own generic-ballot average (aggregator fallback, flagged).
    weights=(a, b) forces the fixed national:poll combination; otherwise cfg.swing.combine decides.
    incumbent_sign: {contest key -> +1 (D incumbent) / -1 (R incumbent)}; shifts the prior by cfg.swing.incumbent_pts.
    demo_dev: {state_po -> D_s}, the state's demographic deviation from the national swing (swing/demographic.py);
    adds kappa * D_s to the prior mean and to the unpolled fallback. None = plain national prior."""
    contests = contests or {}
    keys = list(contests) if contests else sorted(senate.state_po.unique()) if len(senate) else []
    res = run_poll_averages(generic, senate, as_of, cfg, ratings, rcv_states, states=keys or None)
    gb = res.generic
    gb_margin = gb_override if gb_override is not None else gb.margin
    gb_source = "own_average" if gb_override is None else "aggregator_median"
    if not np.isfinite(gb_margin):
        raise ValueError(f"no generic-ballot polls usable as of {as_of}")
    s_nat = national.national_swing(gb_margin, npv_margin)
    a, b = weights or (cfg.swing.weights.national, cfg.swing.weights.state_poll)
    fixed = weights is not None or cfg.swing.combine == "fixed"
    incumbent_sign = incumbent_sign or {}
    demo_dev = demo_dev or {}
    kappa = cfg.swing.demographic_prior.kappa
    m0 = baselines.set_index("state_po").m0
    rows = []
    for key in keys or []:
        st = contests.get(key, key)
        avg = res.states.get(key)
        m0_s = float(m0[st])
        polled = avg is not None and state_mod.is_polled(avg, cfg.swing.state)
        s_poll = state_mod.state_poll_swing(avg.margin, m0_s) if polled else np.nan
        n_eff = avg.n_eff if avg else 0.0
        s_demo = kappa * float(demo_dev.get(st, 0.0))
        s_base = s_nat + s_demo  # national swing moved by the state's demographic mix
        s_prior = s_base + cfg.swing.incumbent_pts * incumbent_sign.get(key, 0)
        if fixed:
            swing, source = combine.state_swing(s_base, s_poll, a, b, polled, cfg.swing.scale_by_poll_volume,
                                                avg.n_eff if avg else None, cfg.swing.n_ref)
            w_poll = (b / (a + b)) if polled else 0.0
            poll_var, post_sd = np.nan, np.nan
        else:
            swing, source, w_poll, poll_var, post_sd = combine.precision_swing(
                s_prior, s_poll, n_eff, cfg.polls.sigma_poll, cfg.swing.precision, polled, s_fallback=s_base)
        swing, mu = combine.state_swing_with_market(swing, None, 0.0)  # no market ingest in Phase 2
        rows.append({"contest": key, "state_po": st, "m0": m0_s, "polled": bool(polled),
                     "poll_margin": avg.margin if polled else np.nan, "n_polls": avg.n_polls if avg else 0,
                     "n_eff": n_eff, "s_poll": s_poll, "s_nat": s_nat, "s_demo": s_demo, "s_prior": s_prior,
                     "swing": swing,
                     "w_poll": w_poll, "poll_var": poll_var, "post_sd": post_sd, "swing_source": source, "market_weight": mu, "proj_margin": m0_s + swing})
    nat = {"gb_margin": float(gb_margin), "gb_source": gb_source, "gb_n_polls": gb.n_polls, "gb_n_eff": gb.n_eff,
           "gb_se": gb.se, "npv_baseline": float(npv_margin), "s_nat": float(s_nat), "combine": "fixed" if fixed else "precision", "a": a, "b": b,
           "delta_lv": res.delta_lv, "as_of": str(as_of)}
    return {"national": nat, "states": pd.DataFrame(rows), "polling": res}
