"""Live Phase 2 run: processed polls + 2024 baseline -> state swing table -> output/summary.json (plan §8.1 `model`)."""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import structlog

from .config import ROOT, Settings, load_config
from .export.to_json import build_summary, write_summary
from .ingest._base import manual_dir, processed_dir
from .polls.weights import margin_2p, ratings_lookup
from .swing import baseline as base
from .swing.model import run_state_model

log = structlog.get_logger()
OUTPUT = ROOT / "output"
AGG_DISAGREE_PTS = 1.5  # plan §4.2 diagnostic: |ours - median(aggregators)|


def load_baseline(year: int = 2024) -> pd.DataFrame:
    """State votes for the baseline year: summed processed county rows if present, else the state-level manual
    table (data/manual/backtest/pres_state_<year>.csv, built by scripts/build_backtest_data.py)."""
    pc = processed_dir() / "pres_county.parquet"
    if pc.exists():
        d = pd.read_parquet(pc)
        d = d[d.year == year]
        if len(d):
            return d.groupby("state_po", as_index=False)[["votes_d", "votes_r"]].sum()
    return pd.read_csv(manual_dir() / "backtest" / f"pres_state_{year}.csv")


def aggregator_median(path=None) -> tuple[float, int]:
    p = path or manual_dir() / "aggregator_headlines.csv"
    if not p.exists():
        return float("nan"), 0
    d = pd.read_csv(p)
    if d.empty:
        return float("nan"), 0
    return float(np.median(margin_2p(d.d_pct, d.r_pct))), len(d)


def run_model(cfg: Settings | None = None, as_of: date | None = None, write: bool = True) -> dict:
    cfg = cfg or load_config()
    as_of = as_of or cfg.resolved_as_of()
    races = pd.read_csv(manual_dir() / "races_2026.csv", dtype=str, keep_default_na=False)
    generic = pd.read_parquet(processed_dir() / "generic_polls.parquet")
    senate = pd.read_parquet(processed_dir() / "senate_polls.parquet")
    ratings_p = manual_dir() / "pollster_ratings.csv"
    ratings = ratings_lookup(pd.read_csv(ratings_p)) if ratings_p.exists() else {}
    bl = base.state_baselines(load_baseline(cfg.baseline.year))
    npv = base.national_margin(load_baseline(cfg.baseline.year))
    rcv = set(races.state_po[races.rcv.str.lower() == "true"])
    contests = {s: s for s in races.state_po}
    agg, n_agg = aggregator_median()
    try:
        out = run_state_model(generic, senate, bl, npv, as_of, cfg, ratings, contests=contests, rcv_states=rcv)
    except ValueError:
        # No usable raw generic-ballot polls (the Wikipedia raw-poll source is unavailable, see data dictionary):
        # fall back to the median of the hand-entered aggregator headlines and say so in the output.
        if not np.isfinite(agg):
            raise
        log.warning("warning", code="GB_AGGREGATOR_FALLBACK", median=round(agg, 2), n_aggregators=n_agg)
        out = run_state_model(generic, senate, bl, npv, as_of, cfg, ratings, contests=contests, rcv_states=rcv,
                              gb_override=agg)
        out["national"]["gb_source"] = "aggregator_median_fallback"
        out["national"]["gb_n_polls"] = n_agg
    nat = out["national"]
    if nat["gb_source"] == "own_average" and np.isfinite(agg) and abs(nat["gb_margin"] - agg) > AGG_DISAGREE_PTS:
        log.warning("warning", code="GB_VS_AGGREGATORS", ours=round(nat["gb_margin"], 2), aggregators=round(agg, 2))
    ev_p = OUTPUT / "early_vote_component.csv"  # separate component from `make earlyvote` (Phase 4)
    ev = pd.read_csv(ev_p).set_index("state_po").E.to_dict() if ev_p.exists() else None
    summary = build_summary(nat, out["states"], races, nat["a"], nat["b"], early_vote=ev)
    if write:
        OUTPUT.mkdir(exist_ok=True)
        write_summary(summary, OUTPUT / "summary.json")
        out["states"].to_csv(OUTPUT / "state_swing_2026.csv", index=False)
        audit_dir = OUTPUT / "poll_audit"
        audit_dir.mkdir(exist_ok=True)
        for st, avg in out["polling"].states.items():
            if avg.available:
                cols = ["pollster", "field_end", "n", "pop", "margin", "delta", "h", "m_adj", "w", "w_hat"]
                avg.weights_df[[c for c in cols if c in avg.weights_df]].to_csv(audit_dir / f"{st}.csv", index=False)
        (OUTPUT / "national_swing.json").write_text(json.dumps(nat, indent=2, default=str), encoding="utf-8")
    return {"summary": summary, "states": out["states"], "national": nat, "polling": out["polling"]}
