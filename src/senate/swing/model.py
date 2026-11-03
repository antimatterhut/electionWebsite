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
                    weights: tuple[float, float] | None = None, gb_override: float | None = None) -> dict:
    """Returns {"national": {...}, "states": DataFrame, "polling": PollingResult}.

    baselines: state_po, m0. contests: {contest key -> state_po} (default: each race keyed by its state; specials
    use e.g. 'MN-S'). gb_override replaces the own generic-ballot average (aggregator fallback, flagged)."""
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
    m0 = baselines.set_index("state_po").m0
    rows = []
    for key in keys or []:
        st = contests.get(key, key)
        avg = res.states.get(key)
        m0_s = float(m0[st])
        polled = avg is not None and state_mod.is_polled(avg, cfg.swing.state)
        s_poll = state_mod.state_poll_swing(avg.margin, m0_s) if polled else np.nan
        swing, source = combine.state_swing(s_nat, s_poll, a, b, polled, cfg.swing.scale_by_poll_volume,
                                            avg.n_eff if avg else None, cfg.swing.n_ref)
        swing, mu = combine.state_swing_with_market(swing, None, 0.0)  # no market ingest in Phase 2
        rows.append({"contest": key, "state_po": st, "m0": m0_s, "polled": bool(polled),
                     "poll_margin": avg.margin if polled else np.nan, "n_polls": avg.n_polls if avg else 0,
                     "n_eff": avg.n_eff if avg else 0.0, "s_poll": s_poll, "s_nat": s_nat, "swing": swing,
                     "swing_source": source, "market_weight": mu, "proj_margin": m0_s + swing})
    nat = {"gb_margin": float(gb_margin), "gb_source": gb_source, "gb_n_polls": gb.n_polls, "gb_n_eff": gb.n_eff,
           "gb_se": gb.se, "npv_baseline": float(npv_margin), "s_nat": float(s_nat), "a": a, "b": b,
           "delta_lv": res.delta_lv, "as_of": str(as_of)}
    return {"national": nat, "states": pd.DataFrame(rows), "polling": res}
