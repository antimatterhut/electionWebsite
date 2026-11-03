"""Stage `earlyvote`: early-vote component E_s and county omega^EV per race state (plan §6.9).

Writes processed/early_vote_weights.parquet (geoid, group, omega_base, omega_ev, state_po) which `make county` uses as
the final weights, and output/early_vote_component.csv (the separately exported component, `components.early_vote`)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import structlog

from ..config import ROOT, Settings, load_config
from ..ei import inputs as I
from ..county.construct import omega_groups
from ..ei.groups import GROUPS
from ..ingest._base import manual_dir, processed_dir, stamp, write_parquet
from . import compare as C
from . import weights as W

log = structlog.get_logger()
OUTPUT = ROOT / "output"


def _manual(name: str) -> pd.DataFrame | None:
    p = manual_dir() / name
    return pd.read_csv(p, dtype={"geoid": str}) if p.exists() else None


def _hist_county_ev(hist: pd.DataFrame, state: str, d: float, cfg: Settings, rules) -> pd.Series | None:
    """Weighted average of county cumulative ballots at the same days out over the cycles that have county data."""
    w = C.cycle_weights(None, cfg.earlyvote, sorted(int(c) for c in hist.cycle.unique()))
    parts = []
    for c, a in w.items():
        s = C.county_ev(hist, state, c, d, C.period_scale(rules, state, c))
        if len(s):
            parts.append((a, s))
    if not parts:
        return None
    tw = sum(a for a, _ in parts)
    return sum(a / tw * s.fillna(0.0) for a, s in parts)


def state_component(state: str, cfg: Settings, daily: pd.DataFrame, hist: pd.DataFrame, n_ig: pd.DataFrame,
                    m0: pd.Series, rules=None, finals=None, party_group=None, age_share: pd.DataFrame | None = None
                    ) -> dict:
    """Component for one state: comparison table, ev_detail, E_s (capped) and omega^EV."""
    ev = cfg.earlyvote
    q = None
    if party_group is not None and len(party_group[party_group.state_po == state]):
        q = W.party_to_group_matrix(party_group[party_group.state_po == state])
    usable = [d for d in C.DIMS if d != "party" or q is not None]
    if age_share is None:
        usable = [d for d in usable if d != "age_bin"]
    comp = C.pick(daily, hist, state, ev, rules, finals, usable_dims=usable)
    detail = C.ev_detail(daily, state, comp)
    out = {"state_po": state, "ev_detail": detail, "dim": comp.dim if comp else None,
           "as_of_days_out": C.as_of_days_out(daily, state), "comparison": comp}
    psi, blend = None, None
    if comp is not None and comp.dim is not None:
        tab = comp.table.set_index("category")
        ns = n_ig.sum()
        age_base = None
        if comp.dim == "age_bin":
            a = age_share.reindex(n_ig.index).fillna(0.0)
            age_base = a.mul(n_ig.sum(axis=1), axis=0).sum() / n_ig.values.sum()
        fb = W.base_by_category(comp.dim, list(tab.index), ns, q, age_base)
        psi = W.category_psi(tab.final_hat, fb)
        out["psi"] = psi
    if detail in ("full", "county_only"):
        now = C.county_ev(daily, state, 2026, out["as_of_days_out"])
        h = _hist_county_ev(hist, state, out["as_of_days_out"], cfg, rules)
        if len(now) and h is not None:
            blend = W.county_blend(now, h)
    model = W.EVModel(n_ig, m0, comp.dim if comp else None, psi, q,
                      age_share if comp is not None and comp.dim == "age_bin" else None, blend,
                      ev.shrink, ev.county_blend_kappa)
    if detail in ("total_only", "none"):  # uniform psi: no effect on the margin
        model.psi, model.blend = None, None
    cap = W.apply_cap(model, ev.cap_pts)
    out.update(cap, model=model)
    return out


def run_earlyvote(cfg: Settings | None = None, write: bool = True) -> pd.DataFrame:
    cfg = cfg or load_config()
    proc = processed_dir()
    rd = lambda n: pd.read_parquet(proc / n) if (proc / n).exists() else pd.DataFrame()  # noqa: E731
    daily, hist = rd("early_vote_daily.parquet"), rd("early_vote_hist.parquet")
    rules, finals, pg = _manual("ev_rules.csv"), _manual("ev_final.csv"), _manual("ev_party_group.csv")
    inp = I.load_inputs(cfg)
    geo = inp["geo"].set_index("geoid")
    v24 = inp["v24"].set_index("geoid")
    m0 = 100.0 * (v24.votes_d - v24.votes_r) / (v24.votes_d + v24.votes_r)
    ei = pd.read_parquet(proc / "ei_group_vote.parquet")
    ei["state_po"] = ei.geoid.map(geo.state_po)
    omega = omega_groups(ei[["geoid", "state_po", "group", "n_group"]].astype({"group": str}), cfg.turnout.dropoff, GROUPS)
    age = inp["age"]
    age_share = age.pivot(index="geoid", columns="age_bin", values="cvap_share") if age is not None and len(age) else None
    races = pd.read_csv(manual_dir() / "races_2026.csv", dtype=str, keep_default_na=False)
    rows, wts = [], []
    for st in sorted(races.state_po.unique()):
        ids = geo.index[(geo.state_po == st) & geo.index.isin(omega.index)]
        if len(ids) == 0 or (daily.empty and hist.empty):
            rows.append(_row(st, {"ev_detail": "none", "E": 0.0, "E_raw": 0.0, "kappa": 1.0, "cap_binding": False,
                                  "dim": None, "as_of_days_out": None}))
            continue
        r = state_component(st, cfg, daily, hist, omega.reindex(ids), m0.reindex(ids), rules, finals, pg,
                            age_share.reindex(ids) if age_share is not None else None)
        rows.append(_row(st, r))
        om = r["omega"]
        wts.append(pd.concat({"omega_base": omega.reindex(ids).stack(), "omega_ev": om.stack()}, axis=1)
                   .rename_axis(["geoid", "group"]).reset_index().assign(state_po=st))
    comp = pd.DataFrame(rows)
    if write:
        OUTPUT.mkdir(exist_ok=True)
        comp.to_csv(OUTPUT / "early_vote_component.csv", index=False)
        if wts:
            write_parquet(stamp(pd.concat(wts, ignore_index=True), "earlyvote:weights", "phase4-0", "ok"),
                          proc / "early_vote_weights.parquet")
        elif (proc / "early_vote_weights.parquet").exists():
            (proc / "early_vote_weights.parquet").unlink()  # stale weights must not feed `make county`
        write_days_out(daily, hist, list(comp.state_po[comp.ev_detail != "none"]))
        (OUTPUT / "early_vote_summary.json").write_text(json.dumps(summary(comp), indent=2, default=str), encoding="utf-8")
    return comp


def _row(st: str, r: dict) -> dict:
    c = r.get("comparison")
    tr = c.total_ratio if c is not None else {}
    total = None if c is None else float(c.table.final_hat.sum())  # projected final ballots (total turnout update)
    return {"state_po": st, "ev_detail": r["ev_detail"], "dim": r["dim"], "as_of_days_out": r["as_of_days_out"],
            "E_raw": r["E_raw"], "E": r["E"], "kappa": r["kappa"], "cap_binding": r["cap_binding"],
            "projected_total_ballots": total, "total_ratio_2022": tr.get(2022), "total_ratio_2018": tr.get(2018), "total_ratio_2024": tr.get(2024)}


def summary(comp: pd.DataFrame) -> dict:
    return {"n_states": len(comp), "ev_detail_counts": comp.ev_detail.value_counts().to_dict(),
            "not_full": comp.loc[comp.ev_detail != "full", ["state_po", "ev_detail"]].to_dict("records"),
            "component_E": {r.state_po: round(float(r.E), 4) for r in comp.itertuples()},
            "cap_binding": [r.state_po for r in comp.itertuples() if r.cap_binding]}


def write_days_out(daily: pd.DataFrame, hist: pd.DataFrame, states: list[str]) -> None:
    """output/early_vote/days_out_<ST>.csv (+ PNG if matplotlib is installed): cumulative total ballots by days out."""
    d = OUTPUT / "early_vote"
    d.mkdir(parents=True, exist_ok=True)
    allv = pd.concat([x for x in (daily, hist) if len(x)], ignore_index=True) if (len(daily) or len(hist)) else None
    if allv is None:
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        plt = None
    for st in states:
        frames = []
        for c in sorted(allv.cycle.unique()):
            s = C._select(allv, st, int(c), None)
            if len(s):
                frames.append(s[["cycle", "days_out", "ballots"]])
        if not frames:
            continue
        cur = pd.concat(frames)
        cur.to_csv(d / f"days_out_{st}.csv", index=False)
        if plt is not None:
            fig, ax = plt.subplots(figsize=(6, 3.5))
            for c, g in cur.groupby("cycle"):
                ax.plot(g.days_out, g.ballots, label=str(c), lw=2.5 if c == 2026 else 1.2)
            ax.invert_xaxis()
            ax.set(xlabel="days before Election Day", ylabel="cumulative ballots", title=f"{st} early vote")
            ax.legend()
            fig.tight_layout()
            fig.savefig(d / f"days_out_{st}.png", dpi=110)
            plt.close(fig)
