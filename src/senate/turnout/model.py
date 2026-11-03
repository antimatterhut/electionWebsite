"""Turnout model (plan §6.10): 2026 group turnout weights, state totals and the turnout-composition component T_s.

omega_ig^base = V_ig^2024 * d_g * c_s, with c_s chosen so sum_i omega_i = T_s^2026 and
T_s^2026 = V_s^2024 * rho_s * (1 + beta |S_nat|),  rho_s = w1 V22/V20 + w2 V18/V16.
T_s (the margin component) = m0_s(omega^base) - m0_s^2024, m0_s(omega) = sum_i nu_i m0_i.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Settings
from ..ei.groups import GROUPS

MIN_TWO_PARTY_SHARE = 0.10  # a Senate race where one side took < 10% of the two-party vote is uncontested: drop it


def midterm_totals(truth: pd.DataFrame) -> pd.Series:
    """State two-party Senate votes from a senate_truth table (regular races only, contested only)."""
    t = truth[truth.race == "regular"].copy()
    tot = t.votes_d + t.votes_r
    ok = (np.minimum(t.votes_d, t.votes_r) / tot.replace(0, np.nan)) >= MIN_TWO_PARTY_SHARE
    return tot[ok].groupby(t.state_po[ok]).sum()


def pres_totals(pres: pd.DataFrame) -> pd.Series:
    return (pres.votes_d + pres.votes_r).groupby(pres.state_po).sum()


def rho_state(v22: pd.Series, v20: pd.Series, v18: pd.Series, v16: pd.Series, states: list[str],
              weights: dict[str, float]) -> pd.DataFrame:
    """rho_s per state. A state lacking a contested midterm Senate race in a cycle takes the pooled median ratio of
    the states that have one (flagged in `rho_source`); a state lacking both takes the weighted pooled values."""
    w22, w18 = weights["r22_20"], weights["r18_16"]
    r22 = (v22 / v20).replace([np.inf, -np.inf], np.nan).dropna()
    r18 = (v18 / v16).replace([np.inf, -np.inf], np.nan).dropna()
    p22 = float(r22.median()) if len(r22) else np.nan
    p18 = float(r18.median()) if len(r18) else np.nan
    rows = []
    for s in states:
        a, b = r22.get(s, np.nan), r18.get(s, np.nan)
        src = "state" if np.isfinite(a) and np.isfinite(b) else "partial_pooled"
        a = a if np.isfinite(a) else p22
        b = b if np.isfinite(b) else p18
        if not (np.isfinite(a) or np.isfinite(b)):
            raise ValueError("no midterm/presidential turnout ratios available for rho_s")
        if not np.isfinite(a):
            val = b
        elif not np.isfinite(b):
            val = a
        else:
            val = (w22 * a + w18 * b) / (w22 + w18)
        if src == "partial_pooled" and s not in r22.index and s not in r18.index:
            src = "pooled"
        rows.append({"state_po": s, "rho": float(val), "rho_source": src})
    return pd.DataFrame(rows).set_index("state_po")


def state_turnout_totals(v24: pd.Series, rho: pd.Series, s_nat: float, beta: float) -> pd.Series:
    """T_s^2026 = V_s^2024 * rho_s * (1 + beta*|S_nat|) (environment bump: high-swing years raise turnout)."""
    return v24 * rho.reindex(v24.index) * (1.0 + beta * abs(s_nat))


def group_omega(n_group: pd.DataFrame, dropoff: dict[str, float], t_state: pd.Series,
                state_of: pd.Series) -> pd.DataFrame:
    """omega^base county x group, scaled so each state's total equals t_state[s]. n_group: geoid x group (2024 voters)."""
    raw = n_group[GROUPS] * pd.Series(dropoff)[GROUPS].to_numpy()
    st = state_of.reindex(raw.index)
    tot = raw.sum(axis=1).groupby(st).transform("sum")
    c = st.map(t_state).to_numpy() / tot.to_numpy()
    return raw.mul(c, axis=0)


def rescale_to_state_total(omega: pd.DataFrame, t_state: pd.Series, state_of: pd.Series) -> pd.DataFrame:
    st = state_of.reindex(omega.index)
    tot = omega.sum(axis=1).groupby(st).transform("sum")
    return omega.mul(st.map(t_state).to_numpy() / tot.to_numpy(), axis=0)


def state_margin(omega: pd.DataFrame, m0: pd.Series, state_of: pd.Series) -> pd.Series:
    """m0_s(omega) = sum_i nu_i m0_i with nu_i the county share of the state's expected votes."""
    w = omega.sum(axis=1)
    st = state_of.reindex(omega.index)
    return (w * m0.reindex(omega.index)).groupby(st).sum() / w.groupby(st).sum()


def turnout_component(n_group: pd.DataFrame, omega_base: pd.DataFrame, m0: pd.Series, state_of: pd.Series
                      ) -> pd.Series:
    """T_s = m0_s(omega^base) - m0_s^2024 (2024 weights = actual 2024 two-party votes = sum_g n_ig)."""
    return state_margin(omega_base, m0, state_of) - state_margin(n_group[GROUPS], m0, state_of)


def build_turnout(n_group: pd.DataFrame, m0: pd.Series, state_of: pd.Series, t_state: pd.Series,
                  cfg: Settings, omega_ev: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.Series]:
    """Returns (turnout table geoid, state_po, group, omega_base, omega_ev, share_of_state; T_s series).

    omega_ev (Phase 4 early-vote weights) is rescaled to the same state totals; absent -> omega_ev = omega_base."""
    base = group_omega(n_group, cfg.turnout.dropoff, t_state, state_of)
    ev = base if omega_ev is None else rescale_to_state_total(omega_ev.reindex(base.index).combine_first(base),
                                                              t_state, state_of)
    st = state_of.reindex(base.index)
    tot_ev = ev.sum(axis=1).groupby(st).transform("sum")
    long = pd.concat({"omega_base": base.stack(), "omega_ev": ev.stack(),
                      "share_of_state": ev.div(tot_ev, axis=0).stack()}, axis=1)
    long = long.rename_axis(["geoid", "group"]).reset_index()
    long["state_po"] = long.geoid.map(state_of)
    return long[["geoid", "state_po", "group", "omega_base", "omega_ev", "share_of_state"]], \
        turnout_component(n_group, base, m0, state_of)
