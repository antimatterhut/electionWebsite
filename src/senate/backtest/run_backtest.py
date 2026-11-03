"""State-level backtests for 2018 (baseline 2016) and 2022 (baseline 2020), plan §7.1-7.4.

Same code path as the live run (`swing.model.run_state_model`); only information dated on/before the cutoff is used.
Inputs are the committed tables under data/manual/backtest/ (built by scripts/build_backtest_data.py)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from ..config import ROOT, Settings, load_config
from ..polls.weights import ratings_lookup
from ..swing import baseline as base
from ..swing.model import run_state_model
from . import metrics as M
from . import sim_backtest as SB

DATA = ROOT / "data" / "manual" / "backtest"
OUT = ROOT / "output" / "backtest"
CYCLES = {2018: {"baseline_year": 2016, "election_day": date(2018, 11, 6)},
          2022: {"baseline_year": 2020, "election_day": date(2022, 11, 8)}}
# (label, fixed (national, poll) weights or None for the configured combine mode). The precision row uses cfg as given.
SENSITIVITY = [("fixed 2:1 (old default)", (2.0, 1.0)), ("fixed 60:40", (0.6, 0.4)), ("precision (default)", None)]
GRID_SIGMA_PRIOR = (3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0)
GRID_SIGMA_BIAS = (0.0, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
THRESH_STATE_RMSE, AIM_STATE_RMSE, BIAS_MAX = 5.0, 4.0, 1.5
SPECIAL_SUFFIX = "-S"  # contest key for special elections, e.g. 'MN-S'; its baseline is the state's


def contest_key(state_po: pd.Series, race: pd.Series) -> pd.Series:
    return state_po.where(race != "special", state_po + SPECIAL_SUFFIX)


def load_cycle(cycle: int, data_dir: Path = DATA) -> dict:
    cd = data_dir / str(cycle)
    senate = pd.read_csv(cd / "senate_polls.csv", parse_dates=["field_start", "field_end"])
    senate["state_po"] = contest_key(senate.state_po, senate.race)
    generic = pd.read_csv(cd / "generic_polls.csv", parse_dates=["field_start", "field_end"])
    truth = pd.read_csv(cd / "senate_truth.csv")
    truth["contest"] = contest_key(truth.state_po, truth.race)
    truth["actual_margin"] = [base.baseline_margin(d, r) for d, r in zip(truth.votes_d, truth.votes_r)]
    pres = pd.read_csv(data_dir / f"pres_state_{CYCLES[cycle]['baseline_year']}.csv")
    ratings_path = ROOT / "data" / "manual" / "pollster_ratings.csv"
    ratings = ratings_lookup(pd.read_csv(ratings_path)) if ratings_path.exists() else {}
    return {"senate": senate, "generic": generic, "truth": truth, "pres": pres, "ratings": ratings}


def incumbent_signs(truth: pd.DataFrame) -> dict[str, int]:
    """+1 where the D-side candidate is the incumbent, -1 for the R side (names carry an '(incumbent)' tag)."""
    d = truth.dside_name.str.contains("incumbent", case=False, na=False)
    r = truth.rside_name.str.contains("incumbent", case=False, na=False)
    return dict(zip(truth.contest, d.astype(int) - r.astype(int)))


def with_precision(cfg: Settings, **kw) -> Settings:
    """cfg copy with swing.precision / swing.incumbent_pts / swing.combine overridden (for grid searches)."""
    sw = cfg.swing
    upd = {k: kw.pop(k) for k in ("combine", "incumbent_pts") if k in kw}
    prec = sw.precision.model_copy(update=kw)
    return cfg.model_copy(update={"swing": sw.model_copy(update={**upd, "precision": prec})})


def run_cycle(cycle: int, cfg: Settings, days_before: int | None = None, weights: tuple[float, float] | None = None,
              data: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """One as-of run. Returns (per-race frame with errors, national dict)."""
    d = data or load_cycle(cycle)
    days = cfg.backtest.as_of_days_before if days_before is None else days_before
    as_of = CYCLES[cycle]["election_day"] - timedelta(days=days)
    bl = base.state_baselines(d["pres"])
    npv = base.national_margin(d["pres"])
    truth = d["truth"]
    contests = dict(zip(truth.contest, truth.state_po))
    out = run_state_model(d["generic"], d["senate"], bl, npv, as_of, cfg, d["ratings"], contests=contests,
                          weights=weights, incumbent_sign=incumbent_signs(truth))
    df = out["states"].merge(truth[["contest", "actual_margin", "dside_name", "rside_name"]], on="contest")
    df["naive_margin"] = df.m0 + out["national"]["s_nat"]
    df["error"] = df.proj_margin - df.actual_margin
    df["cycle"] = cycle
    return df, out["national"]


def run_backtest(cfg: Settings | None = None, out_dir: Path = OUT, data_dir: Path = DATA) -> dict:
    cfg = cfg or load_config()
    sigma = cfg.swing.market.sigma_pts
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict = {"cycles": {}, "sensitivity": {}, "rolling": {}}
    for cycle in CYCLES:
        data = load_cycle(cycle, data_dir)
        df, nat = run_cycle(cycle, cfg, data=data)
        (out_dir / str(cycle)).mkdir(exist_ok=True)
        df.to_parquet(out_dir / str(cycle) / "state_errors.parquet", index=False)
        results["cycles"][cycle] = {"national": nat, "metrics": M.state_metrics(df, sigma),
                                    "polled_share": float(df.polled.mean()), "frame": df,
                                    "sim": SB.run_cycle_sim(df, cycle, cfg)}
        for label, w in SENSITIVITY:
            sdf, _ = run_cycle(cycle, cfg, weights=w, data=data)  # w None -> configured combine mode
            sm = M.state_metrics(sdf, sigma)
            sm["brier_sim"] = SB.run_cycle_sim(sdf, cycle, cfg)["brier"]
            results["sensitivity"].setdefault(label, {})[cycle] = sm
        for days in (30, 60, 90):
            try:
                rdf, _ = run_cycle(cycle, cfg, days_before=days, data=data)
                results["rolling"].setdefault(cycle, {})[days] = M.state_metrics(rdf, sigma)
            except ValueError as e:  # no generic polls that early
                results["rolling"].setdefault(cycle, {})[days] = {"error": str(e)}
    results["gate"] = gate(results)
    (out_dir / "sensitivity.md").write_text(sensitivity_md(results), encoding="utf-8")
    (out_dir / "report.md").write_text(report_md(results, cfg), encoding="utf-8")
    slim = {"cycles": {c: {k: v for k, v in r.items() if k != "frame"} for c, r in results["cycles"].items()},
            "sensitivity": results["sensitivity"], "rolling": results["rolling"], "gate": results["gate"]}
    (out_dir / "metrics.json").write_text(json.dumps(slim, indent=2, default=str), encoding="utf-8")
    return results


def pooled_metrics(frames: list[pd.DataFrame]) -> dict:
    err = pd.concat([f.error for f in frames]).to_numpy()
    return {"rmse": M.rmse(err), "bias": M.bias(err), "n": int(len(err))}


def grid_search(cfg: Settings | None = None, data_dir: Path = DATA, sigma_prior=GRID_SIGMA_PRIOR,
                sigma_bias=GRID_SIGMA_BIAS, **fixed) -> pd.DataFrame:
    """Pooled 2018+2022 state RMSE / bias for each (sigma_prior, sigma_bias) under precision weighting."""
    cfg = cfg or load_config()
    data = {c: load_cycle(c, data_dir) for c in CYCLES}
    rows = []
    for sp in sigma_prior:
        for sb in sigma_bias:
            c = with_precision(cfg, combine="precision", sigma_prior=sp, sigma_bias=sb, **fixed)
            fr = [run_cycle(cy, c, data=data[cy])[0] for cy in CYCLES]
            pm = pooled_metrics(fr)
            rows.append({"sigma_prior": sp, "sigma_bias": sb, "rmse": pm["rmse"], "bias": pm["bias"],
                         "abs_bias": abs(pm["bias"]), **{f"rmse_{cy}": M.rmse(f.error) for cy, f in zip(CYCLES, fr)}})
    return pd.DataFrame(rows).sort_values(["rmse", "abs_bias"]).reset_index(drop=True)


def gate(results: dict) -> dict:
    """Phase 2 DoD: the plan §7.4 rows that can be evaluated at state level."""
    checks = {}
    for cycle, r in results["cycles"].items():
        m = r["metrics"]
        checks[cycle] = {
            "state_rmse<=5.0": m["state_rmse"] <= THRESH_STATE_RMSE,
            "state_rmse<=4.0 (aim)": m["state_rmse"] <= AIM_STATE_RMSE,
            "not_worse_than_uniform_swing": m["state_rmse"] <= m["naive_rmse"],
            "abs_bias<=1.5": abs(m["bias"]) <= BIAS_MAX,
            **{f"{k} (simulation)": v for k, v in SB.gate(r["sim"]).items()},
        }
    return checks


def sensitivity_md(results: dict) -> str:
    lines = ["| Combination | 2022 RMSE | 2022 bias | 2022 Brier | 2018 RMSE | 2018 bias | 2018 Brier |",
             "|---|---|---|---|---|---|---|"]
    for label, _ in SENSITIVITY:
        s = results["sensitivity"][label]
        name = f"**{label}**" if label.startswith("precision") else label
        lines.append(f"| {name} | {s[2022]['state_rmse']:.2f} | {s[2022]['bias']:+.2f} | {s[2022]['brier_sim']:.3f} | "
                     f"{s[2018]['state_rmse']:.2f} | {s[2018]['bias']:+.2f} | {s[2018]['brier_sim']:.3f} |")
    lines += ["", "Brier from the Phase 5 state-level simulation. Precision row uses the configured sigma_prior/sigma_bias "
              "(tuned by `grid_search` on the pooled 2018+2022 backtests)."]
    return "\n".join(lines) + "\n"


def report_md(results: dict, cfg: Settings) -> str:
    L = ["# Senate state-level backtest (Phases 2 + 5)", "",
         f"As-of cutoff: election day minus {cfg.backtest.as_of_days_before} day(s); polls dated after the cutoff are "
         "never used. Truth = certified two-party Senate margin (D-side minus R); baseline = prior presidential "
         "election. Win probabilities and intervals come from the Phase 5 state-level simulation.", ""]
    for cycle, r in results["cycles"].items():
        m, n = r["metrics"], r["national"]
        L += [f"## {cycle} (baseline {CYCLES[cycle]['baseline_year']})", "",
              f"- Generic ballot {n['gb_margin']:+.2f} ({n['gb_n_polls']} polls, n_eff {n['gb_n_eff']:.1f}); "
              f"baseline NPV {n['npv_baseline']:+.2f}; national swing {n['s_nat']:+.2f}; "
              f"LV/RV delta {n['delta_lv']:+.2f}",
              f"- Races {m['n_races']} ({r['polled_share']:.0%} polled); **state RMSE {m['state_rmse']:.2f}**, "
              f"uniform-national-swing RMSE {m['naive_rmse']:.2f}; bias {m['bias']:+.2f}; "
              f"winner accuracy {m['winner_accuracy']:.0%}",
              f"- Simulation: Brier {r['sim']['brier']:.3f}, log-loss {r['sim']['log_loss']:.3f}, 80% interval coverage "
              f"{r['sim']['coverage80']:.2f}; actual D-side wins {r['sim']['actual_d_wins']} of {r['sim']['n_races']} at the "
              f"{r['sim']['actual_seat_percentile']:.0%} percentile of the simulated distribution (mean "
              f"{r['sim']['sim_mean_d_wins']:.1f}, 80% interval {r['sim']['sim_interval80_d_wins'][0]:.0f}-"
              f"{r['sim']['sim_interval80_d_wins'][1]:.0f}); error model: {r['sim']['error_model']['source']}",
              "", "| Check | Pass |", "|---|---|"]
        L += [f"| {k} | {'yes' if v else '**NO**'} |" for k, v in results["gate"][cycle].items()]
        L += ["", "Reliability (simulated win probability, 10 bins):", "", "| Bin | n | mean forecast | observed |",
              "|---|---|---|---|"]
        L += [f"| {b['bin']} | {b['n']} | " + (f"{b['mean_p']:.2f} | {b['observed']:.2f} |" if b["n"] else "- | - |")
              for b in r["sim"]["reliability"]]
        L += ["", "Worst misses:", "", "| Race | Projected | Actual | Error | Polled | n polls |",
              "|---|---|---|---|---|---|"]
        f = r["frame"].reindex(r["frame"].error.abs().sort_values(ascending=False).index).head(8)
        L += [f"| {x.contest} | {x.proj_margin:+.1f} | {x.actual_margin:+.1f} | {x.error:+.1f} | {x.polled} | "
              f"{x.n_polls} |" for x in f.itertuples()]
        L += [""]
    L += ["## Rolling as-of check", "", "| Cycle | Days before | State RMSE | Uniform-swing RMSE | Bias |",
          "|---|---|---|---|---|"]
    for cycle, d in results["rolling"].items():
        for days, m in d.items():
            tail = (f"{m['state_rmse']:.2f} | {m['naive_rmse']:.2f} | {m['bias']:+.2f} |" if "state_rmse" in m
                    else f"n/a ({m['error'][:40]}) | | |")
            L.append(f"| {cycle} | {days} | {tail}")
    L += ["", "## Sensitivity (informational)", "", sensitivity_md(results)]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    run_backtest()
    print((OUT / "report.md").read_text(encoding="utf-8"))
