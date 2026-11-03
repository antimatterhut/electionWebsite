"""Simulation calibration in the backtests (plan §7.3): Brier, log-loss, reliability, interval coverage, seat percentile.

The state-level simulation (no county layer: the backtest tables are state-level) uses the same code and the same
error model as the live run. The error model for a cycle is fitted without that cycle's own misses."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Settings
from ..ingest._base import manual_dir, processed_dir
from ..sim import errors as E
from ..sim import outputs as O
from ..sim import simulate as S
from ..sim.run_sim import build_inputs
from . import metrics as M

BINS = np.linspace(0.0, 1.0, 11)
EPS = 1e-4
BRIER_MAX = 0.10
COVERAGE = (0.70, 0.90)


def _cvap() -> pd.DataFrame | None:
    p = processed_dir() / "cvap_county.parquet"
    return pd.read_parquet(p) if p.exists() else None


def _misses() -> pd.DataFrame:
    p = manual_dir() / "historical_midterm_polling_misses.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def reliability(p: np.ndarray, y: np.ndarray) -> list[dict]:
    """10 equal-width probability bins: count, mean forecast, observed frequency."""
    idx = np.clip(np.digitize(p, BINS[1:-1]), 0, 9)
    out = []
    for b in range(10):
        m = idx == b
        out.append({"bin": f"{BINS[b]:.1f}-{BINS[b + 1]:.1f}", "n": int(m.sum()),
                    "mean_p": float(p[m].mean()) if m.any() else None,
                    "observed": float(y[m].mean()) if m.any() else None})
    return out


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, EPS, 1 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def sim_metrics(df: pd.DataFrame, res: S.SimResult, interval: list[float]) -> dict:
    """df: contest, actual_margin (rows in the simulation's unit order)."""
    st = O.state_table(res, interval).reindex(df.contest)
    p = st.p_dside_win.to_numpy()
    y = (df.actual_margin > 0).astype(float).to_numpy()
    inside = ((df.actual_margin.to_numpy() >= st.lo.to_numpy()) & (df.actual_margin.to_numpy() <= st.hi.to_numpy()))
    wins = (res.margins > 0).sum(axis=1)
    actual_seats = int(y.sum())
    pct = float((wins < actual_seats).mean() + 0.5 * (wins == actual_seats).mean())  # mid-rank percentile
    return {"n_races": int(len(df)), "brier": M.brier(p, y), "log_loss": log_loss(p, y),
            "coverage80": float(inside.mean()), "reliability": reliability(p, y),
            "actual_d_wins": actual_seats, "sim_mean_d_wins": float(wins.mean()),
            "sim_interval80_d_wins": [float(np.quantile(wins, 0.1)), float(np.quantile(wins, 0.9))],
            "actual_seat_percentile": pct, "mean_p_winner": float(np.mean(np.where(y == 1, p, 1 - p)))}


def run_cycle_sim(df: pd.DataFrame, cycle: int, cfg: Settings, n_draws: int | None = None) -> dict:
    """df: run_cycle() frame (contest, state_po, proj_margin, polled, n_eff, actual_margin)."""
    em = E.fit_error_model(_misses(), cfg, exclude_year=cycle)
    st = pd.DataFrame({"m_hat": df.proj_margin.to_numpy(), "polled": df.polled.to_numpy(),
                       "n_eff": df.n_eff.to_numpy(), "state_po": df.state_po.to_numpy()}, index=df.contest.to_numpy())
    inp = build_inputs(st, em, cfg, _cvap())
    res = S.simulate(inp, em, n_draws or cfg.sim.n_draws, cfg.sim.seed, cfg.sim.rho.region_neighbor, cfg.sim.chunk)
    out = sim_metrics(df.reset_index(drop=True), res, cfg.sim.interval)
    out["error_model"] = {"source": em.source, "national": em.national, "region": em.region, "state": em.state}
    return out


def gate(m: dict) -> dict:
    return {"brier<=0.10": m["brier"] <= BRIER_MAX,
            "coverage80_in_0.70-0.90": COVERAGE[0] <= m["coverage80"] <= COVERAGE[1]}
