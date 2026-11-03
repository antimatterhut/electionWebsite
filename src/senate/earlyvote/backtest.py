"""Back-test of the early-vote module on 2022 (plan §6.9 acceptance: projected turnout RMSE <= 3 pts statewide).

2022 is the target; the comparators are the other cycles in early_vote_hist (2018, 2020, 2024 as available, equally
weighted since config.earlyvote.cycle_weights has no 2020 entry). The projection is made `backtest.as_of_days_before`
days out and compared with the certified 2022 final ballots (data/manual/ev_final.csv, all-category row). Error is in
points of CVAP turnout when CVAP is available. No historical files ship in the repo: with none, this reports no_data."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ..config import ROOT, Settings, load_config
from ..geo.fips import FIPS_STATE
from ..ingest._base import manual_dir, processed_dir
from . import compare as C

OUTPUT = ROOT / "output"
THRESHOLD_PTS = 3.0


def backtest_total_turnout(hist: pd.DataFrame, finals: pd.DataFrame, cfg: Settings, days_out: int,
                           cvap: dict[str, float] | None = None, rules: pd.DataFrame | None = None,
                           target: int = 2022) -> pd.DataFrame:
    """One row per state: projected vs actual final ballots at `days_out`, error in turnout pts (or % of actual)."""
    rows = []
    for st in sorted(hist.state_po.unique()):
        comps = sorted(int(c) for c in hist[hist.state_po == st].cycle.unique() if c != target)
        comps = [c for c in comps if not np.isnan(C.final_for(finals, st, c, None, "total"))]
        actual = C.final_for(finals, st, target, None, "total")
        if not comps or np.isnan(actual):
            continue
        w = {c: 1.0 / len(comps) for c in comps}
        cmp_ = C.compare_state(hist, hist, st, None, cfg.earlyvote, rules, finals, target_cycle=target,
                               comparators=comps, weights=w, days_out=days_out)
        if cmp_ is None:
            continue
        hat = float(cmp_.table.final_hat.iloc[0])
        r = {"state_po": st, "projected": hat, "actual": actual, "comparators": ",".join(map(str, comps)),
             "err_pct_of_actual": 100 * (hat - actual) / actual}
        if cvap and st in cvap:
            r["err_pts"] = 100 * (hat - actual) / cvap[st]
        rows.append(r)
    return pd.DataFrame(rows)


def summarize(bt: pd.DataFrame) -> dict:
    if bt.empty:
        return {"status": "no_data", "n_states": 0, "passes_rmse_3pts": None}
    col = "err_pts" if "err_pts" in bt and bt.err_pts.notna().all() else None
    out = {"status": "ok", "n_states": int(len(bt)),
           "rmse_pct_of_actual": float(np.sqrt((bt.err_pct_of_actual ** 2).mean()))}
    if col:
        out["rmse_pts"] = float(np.sqrt((bt.err_pts ** 2).mean()))
        out["passes_rmse_3pts"] = bool(out["rmse_pts"] <= THRESHOLD_PTS)
    else:
        out["passes_rmse_3pts"] = None  # needs CVAP to express error in turnout points
    return out


def run_earlyvote_backtest(cfg: Settings | None = None) -> dict:
    cfg = cfg or load_config()
    proc = processed_dir()
    hp = proc / "early_vote_hist.parquet"
    hist = pd.read_parquet(hp) if hp.exists() else pd.DataFrame()
    fp = manual_dir() / "ev_final.csv"
    finals = pd.read_csv(fp) if fp.exists() else pd.DataFrame()
    rp = manual_dir() / "ev_rules.csv"
    rules = pd.read_csv(rp) if rp.exists() else None
    cvap = None
    cp = proc / "cvap_county.parquet"
    if cp.exists():
        c = pd.read_parquet(cp)
        tot = c.groupby("geoid").cvap.sum()  # race5 categories partition CVAP
        cvap = tot.groupby(tot.index.str[:2].map(FIPS_STATE)).sum().to_dict()
    bt = pd.DataFrame() if hist.empty or finals.empty else backtest_total_turnout(
        hist, finals, cfg, cfg.backtest.as_of_days_before, cvap, rules)
    res = summarize(bt)
    OUTPUT.mkdir(exist_ok=True)
    bt.to_csv(OUTPUT / "early_vote_backtest_2022.csv", index=False)
    (OUTPUT / "early_vote_backtest_2022.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res
