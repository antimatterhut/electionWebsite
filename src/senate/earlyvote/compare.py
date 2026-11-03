"""Same-days-out comparison and final-turnout projection by category (plan §6.9)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import EarlyVote

DIMS = ["party", "age_bin", "race5"]  # preference order when several are reported (plan: party, else age, else race)


def cum_at(days: np.ndarray, vals: np.ndarray, d: float) -> float:
    """Cumulative ballots d days out, linear interpolation on the daily curve.

    Before the first observation voting had not started (0); later than the last observation is unknown (NaN)."""
    o = np.argsort(days)
    x, y = np.asarray(days, float)[o], np.asarray(vals, float)[o]
    if d > x[-1]:
        return 0.0
    if d < x[0]:
        return float("nan")
    return float(np.interp(d, x, y))


def _select(df: pd.DataFrame, state: str, cycle: int, dim: str | None, geo: bool = False) -> pd.DataFrame:
    d = df[(df.state_po == state) & (df.cycle == cycle) & (df["mode"] == "total")]
    d = d[d.geoid.notna()] if geo else d[d.geoid.isna()]
    for k in DIMS:
        d = d[d[k] != "all"] if k == dim else d[d[k] == "all"]
    return d


def curves(df: pd.DataFrame, state: str, cycle: int, dim: str | None) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """{category: (days_out, cumulative ballots)} for one state/cycle/dimension (state level; 'total' if dim is None)."""
    d = _select(df, state, cycle, dim)
    if dim is None:
        return {"total": (d.days_out.to_numpy(), d.ballots.to_numpy())} if len(d) else {}
    return {str(k): (g.days_out.to_numpy(), g.ballots.to_numpy()) for k, g in d.groupby(dim)}


def county_ev(df: pd.DataFrame, state: str, cycle: int, d: float, scale: float = 1.0) -> pd.Series:
    """County cumulative total ballots at d days out (index geoid)."""
    g = _select(df, state, cycle, None, geo=True)
    return pd.Series({k: cum_at(h.days_out.to_numpy(), h.ballots.to_numpy(), d * scale) for k, h in g.groupby("geoid")},
                     dtype=float)


def period_scale(rules: pd.DataFrame | None, state: str, cycle: int) -> float:
    """early_period_scale (cycle's early period length / 2026's) from data/manual/ev_rules.csv; default 1."""
    if rules is None or rules.empty:
        return 1.0
    r = rules[(rules.state_po == state) & (rules.cycle == cycle)]
    return float(r.early_period_scale.iloc[0]) if len(r) else 1.0


def final_for(finals: pd.DataFrame | None, state: str, cycle: int, dim: str | None, cat: str) -> float:
    """Certified final ballots for the category (data/manual/ev_final.csv); NaN if absent."""
    if finals is None or finals.empty:
        return float("nan")
    f = finals[(finals.state_po == state) & (finals.cycle == cycle)]
    for k in DIMS:
        f = f[f[k] == (cat if k == dim else "all")]
    return float(f.final_ballots.iloc[0]) if len(f) else float("nan")


def cycle_weights(dim: str | None, cfg: EarlyVote, available: list[int]) -> dict[int, float]:
    """Party categories use only party_cycles (2018 excluded: R behaviour changed after 2020); others cycle_weights."""
    w = cfg.party_cycle_weights if dim == "party" else cfg.cycle_weights
    w = {c: float(w[c]) for c in available if c in w and (dim != "party" or c in cfg.party_cycles)}
    t = sum(w.values())
    return {c: v / t for c, v in w.items()} if t > 0 else {}


@dataclass
class Comparison:
    state_po: str
    dim: str | None
    days_out: int
    table: pd.DataFrame                                            # one row per category
    total_ratio: dict[int, float] = field(default_factory=dict)   # EV total now / EV^c total at the same days out
    party_level_shift: dict[str, float] = field(default_factory=dict)  # informational only: f^2022_R - f^2018_R


def as_of_days_out(df: pd.DataFrame, state: str, cycle: int = 2026) -> int | None:
    d = _select(df, state, cycle, None)
    return int(d.days_out.min()) if len(d) else None


def compare_state(cur: pd.DataFrame, hist: pd.DataFrame, state: str, dim: str | None, cfg: EarlyVote,
                  rules: pd.DataFrame | None = None, finals: pd.DataFrame | None = None, target_cycle: int = 2026,
                  comparators: list[int] | None = None, weights: dict[int, float] | None = None,
                  days_out: int | None = None) -> Comparison | None:
    """Project each category's final ballots: EV^target_j(d) / sum_c alpha_c f^c_j(d).

    `cur` holds the target cycle (early_vote_daily live; early_vote_hist for the 2022 backtest, which passes
    target_cycle=2022, its comparator cycles, and `days_out`). Returns None if no category can be projected."""
    d0 = days_out if days_out is not None else as_of_days_out(cur, state, target_cycle)
    if d0 is None:
        return None
    avail = comparators if comparators is not None else sorted(int(c) for c in hist.cycle.unique() if c != target_cycle)
    ccurves = {c: curves(hist, state, c, dim) for c in avail}
    rows = []
    for cat, (dy, v) in curves(cur, state, target_cycle, dim).items():
        ev = cum_at(dy, v, d0)
        entry, fs = {"category": cat, "ev_now": ev}, {}
        for c in avail:
            if cat not in ccurves[c]:
                continue
            evc = cum_at(*ccurves[c][cat], d0 * period_scale(rules, state, c))
            fin = final_for(finals, state, c, dim, cat)
            entry[f"ev_{c}"] = evc
            entry[f"rho_{c}"] = ev / evc if np.isfinite(evc) and evc > 0 else np.nan
            if np.isfinite(evc) and np.isfinite(fin) and fin > 0 and evc > 0:
                fs[c] = entry[f"f_{c}"] = evc / fin
        w = weights if weights is not None else cycle_weights(dim, cfg, list(fs))
        w = {c: w[c] for c in fs if c in w}
        tw = sum(w.values())
        if tw > 0 and np.isfinite(ev):
            fbar = sum(w[c] / tw * fs[c] for c in w)
            entry.update(fbar=fbar, final_hat=ev / fbar, cycles_used=",".join(map(str, sorted(w))))
        rows.append(entry)
    tab = pd.DataFrame(rows)
    if tab.empty or "final_hat" not in tab or tab.final_hat.isna().all():
        return None
    total_ratio = {}
    now = curves(cur, state, target_cycle, None).get("total")
    if now:
        for c in avail:
            tc = curves(hist, state, c, None).get("total")
            if tc:
                v = cum_at(*tc, d0 * period_scale(rules, state, c))
                if np.isfinite(v) and v > 0:
                    total_ratio[c] = cum_at(*now, d0) / v
    shift = {}
    if dim == "party" and "f_2018" in tab and "f_2022" in tab:
        r = tab[tab.category == "R"]
        if len(r) and np.isfinite(r.f_2018.iloc[0]) and np.isfinite(r.f_2022.iloc[0]):
            shift["R"] = float(r.f_2022.iloc[0] - r.f_2018.iloc[0])
    return Comparison(state, dim, d0, tab, total_ratio, shift)


def pick(cur: pd.DataFrame, hist: pd.DataFrame, state: str, cfg: EarlyVote, rules=None, finals=None,
         usable_dims: list[str] | None = None, **kw) -> Comparison | None:
    """First dimension in preference order (party > age > race > total) projectable for every category."""
    for dim in (DIMS if usable_dims is None else usable_dims) + [None]:
        c = compare_state(cur, hist, state, dim, cfg, rules, finals, **kw)
        if c is not None and c.table.final_hat.notna().all():
            return c
    return None


def ev_detail(daily: pd.DataFrame, state: str, comp: Comparison | None) -> str:
    """{full, county_only, total_only, none} flag shown in the UI (plan §6.9)."""
    s = daily[(daily.state_po == state) & (daily.cycle == 2026)]
    if s.empty:
        return "none"
    if comp is not None and comp.dim is not None:
        return "full"
    return "county_only" if s.geoid.notna().any() else "total_only"
