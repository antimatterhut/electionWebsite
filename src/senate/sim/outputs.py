"""Simulation outputs (plan §6.12): win probabilities, intervals, seat distribution, tipping points, correlations."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Settings
from .simulate import Q, SimResult


def d_seats_not_up(races: pd.DataFrame, d_caucus_total: int) -> int:
    """H_D = D-caucus seats not up = D-caucus total minus D/I-held seats on the 2026 ballot (plan §6.12)."""
    up = int(races.incumbent_party.isin(["D", "I"]).sum())
    return d_caucus_total - up


def state_table(res: SimResult, interval: list[float]) -> pd.DataFrame:
    lo, hi = np.quantile(res.margins, interval, axis=0)
    return pd.DataFrame({"unit": res.units, "m_hat": res.m_hat, "p_dside_win": (res.margins > 0).mean(axis=0),
                         "median": np.median(res.margins, axis=0), "lo": lo, "hi": hi,
                         "sd": res.margins.std(axis=0)}).set_index("unit")


def county_table(res: SimResult, interval: list[float]) -> pd.DataFrame | None:
    if res.county_dev is None:
        return None
    lo, hi = np.quantile(res.county_dev, interval, axis=0) / Q
    # P(D-side win) needs M_i = m_hat + dev > 0, i.e. dev*0.1 > -m_hat
    p = (res.county_dev / Q + res.county_m_hat[None, :] > 0).mean(axis=0)
    return pd.DataFrame({"geoid": res.county_ids, "m_hat": res.county_m_hat, "p_dside_win": p,
                         "lo": res.county_m_hat + lo, "hi": res.county_m_hat + hi})


def seat_distribution(res: SimResult, h_d: int, threshold: float) -> dict:
    wins = (res.margins > 0).sum(axis=1) + h_d
    n_seats = np.arange(0, h_d + len(res.units) + 1)
    pmf = np.bincount(wins, minlength=len(n_seats)) / len(wins)
    return {"h_d": h_d, "pmf": {int(k): float(v) for k, v in zip(n_seats, pmf) if v > 0},
            "mean": float(wins.mean()), "median": float(np.median(wins)),
            "interval80": [float(np.quantile(wins, 0.1)), float(np.quantile(wins, 0.9))],
            "p_control": float((wins >= threshold).mean()), "threshold": threshold}


def tipping_frequencies(res: SimResult, h_d: int, threshold: float) -> dict[str, float]:
    """Share of draws in which each state is the one that gives D the threshold-th seat (states ranked by D margin)."""
    need = int(threshold) - h_d  # D must win this many contested seats
    n, u = res.margins.shape
    if need < 1 or need > u:
        return {}
    order = np.argsort(-res.margins, axis=1)
    tip = order[:, need - 1]
    cnt = np.bincount(tip, minlength=u) / n
    return {res.units[i]: float(c) for i, c in enumerate(cnt) if c > 0}


def correlations(res: SimResult) -> dict:
    c = np.corrcoef(res.margins.T)
    return {"states": res.units, "corr": np.round(np.nan_to_num(c), 3).tolist()}


def summarize(res: SimResult, races: pd.DataFrame, cfg: Settings) -> dict:
    h_d = d_seats_not_up(races, cfg.sim.d_caucus_total)
    st = state_table(res, cfg.sim.interval)
    return {"n_draws": int(res.margins.shape[0]), "seed": cfg.sim.seed, "interval": cfg.sim.interval,
            "seats": seat_distribution(res, h_d, cfg.sim.control_threshold),
            "tipping": tipping_frequencies(res, h_d, cfg.sim.control_threshold),
            "states": {u: {"p_dside_win": round(float(r.p_dside_win), 4), "m_hat": round(float(r.m_hat), 3),
                           "lo": round(float(r.lo), 3), "hi": round(float(r.hi), 3), "sd": round(float(r.sd), 3)}
                       for u, r in st.iterrows()}}


def write_outputs(res: SimResult, summary: dict, races: pd.DataFrame, cfg: Settings, out: Path,
                  error_model: dict | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    payload = dict(summary)
    if error_model is not None:
        payload["error_model"] = error_model
    (out / "sim_summary.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    state_table(res, cfg.sim.interval).to_csv(out / "sim_states.csv")
    ct = county_table(res, cfg.sim.interval)
    if ct is not None:
        ct.round(4).to_csv(out / "sim_counties.csv", index=False)
    (out / "correlations.json").write_text(json.dumps(correlations(res)), encoding="utf-8")
    arrays = {"state_margin_x10": np.clip(np.rint(res.margins * Q), -32000, 32000).astype(np.int16),
              "units": np.array(res.units)}
    if res.county_dev is not None:
        arrays.update(county_dev_x10=res.county_dev, county_m_hat=res.county_m_hat.astype(np.float32),
                      geoid=np.array(res.county_ids))
    np.savez_compressed(out / "sim_draws.npz", **arrays)  # not published
