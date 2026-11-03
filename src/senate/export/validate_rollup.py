"""Roll-up identity checks (plan §6.11)."""
from __future__ import annotations

import numpy as np
import pandas as pd

TOL = 1e-6


def county_state_margin(counties: pd.DataFrame) -> pd.Series:
    """nu-weighted county projected margin per state; counties: state_po, m_hat, omega (final weights)."""
    w = counties.omega
    return (w * counties.m_hat).groupby(counties.state_po).sum() / w.groupby(counties.state_po).sum()


def check_rollup(counties: pd.DataFrame, components: pd.DataFrame, tol: float = TOL) -> pd.DataFrame:
    """|m_hat_s - (m0_s + S_s + T_s + E_s)| < tol per state.

    components: state_po, m0, swing, T, E (m0 = actual 2024 two-party margin). Returns the per-state table; raises
    AssertionError listing the offenders."""
    got = county_state_margin(counties)
    c = components.set_index("state_po")
    exp = c.m0 + c.swing + c["T"].fillna(0.0) + c.E.fillna(0.0)
    t = pd.DataFrame({"county_rollup": got, "expected": exp}).dropna()
    t["abs_err"] = (t.county_rollup - t.expected).abs()
    bad = t[t.abs_err >= tol]
    if len(bad):
        raise AssertionError(f"roll-up identity violated (tol {tol}):\n{bad.to_string()}")
    return t
