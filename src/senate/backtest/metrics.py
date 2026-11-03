"""Backtest metrics (plan §7.3). State level only in Phase 2."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

Z80 = 1.2815515655446004


def rmse(err: np.ndarray, w: np.ndarray | None = None) -> float:
    err = np.asarray(err, dtype=float)
    return float(np.sqrt(np.average(err**2, weights=w)))


def bias(err: np.ndarray) -> float:
    return float(np.mean(err))


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def provisional_win_prob(proj: np.ndarray, sigma: float) -> np.ndarray:
    """P(D-side wins) = Phi(proj/sigma). Interim stand-in for the Phase 5 simulation (same normal-error idea as the
    market conversion in §6.5.1)."""
    return np.array([_phi(p / sigma) for p in np.asarray(proj, dtype=float)])


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def coverage80(proj: np.ndarray, actual: np.ndarray, sigma: float) -> float:
    return float(np.mean(np.abs(np.asarray(actual) - np.asarray(proj)) <= Z80 * sigma))


def state_metrics(df: pd.DataFrame, sigma: float) -> dict:
    """df: proj_margin, actual_margin, naive_margin (uniform national swing). Adds provisional Brier/coverage."""
    err = (df.proj_margin - df.actual_margin).to_numpy()
    naive_err = (df.naive_margin - df.actual_margin).to_numpy()
    p = provisional_win_prob(df.proj_margin.to_numpy(), sigma)
    y = (df.actual_margin > 0).astype(float).to_numpy()
    return {
        "n_races": int(len(df)), "state_rmse": rmse(err), "bias": bias(err),
        "naive_rmse": rmse(naive_err), "naive_bias": bias(naive_err),
        "brier_provisional": brier(p, y), "coverage80_provisional": coverage80(df.proj_margin, df.actual_margin, sigma),
        "winner_accuracy": float(np.mean((df.proj_margin > 0) == (df.actual_margin > 0))),
    }
