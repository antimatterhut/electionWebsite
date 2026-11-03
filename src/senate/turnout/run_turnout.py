"""Stage `turnout`: processed/turnout.parquet and output/turnout_component.csv (plan §6.10).

Needs processed/ei_group_vote.parquet (`make ei`). Midterm totals come from the committed backtest truth tables
(Senate two-party votes 2022/2018) against the presidential state tables (2020/2016/2024)."""
from __future__ import annotations

import json

import pandas as pd
import structlog

from ..config import ROOT, Settings, load_config
from ..ei import inputs as I
from ..ei.groups import GROUPS
from ..ingest._base import manual_dir, processed_dir, stamp, write_parquet
from . import model as T

log = structlog.get_logger()
OUTPUT = ROOT / "output"


def run_turnout(cfg: Settings | None = None, write: bool = True) -> pd.DataFrame:
    cfg = cfg or load_config()
    proc = processed_dir()
    bt = manual_dir() / "backtest"
    ei = pd.read_parquet(proc / "ei_group_vote.parquet")
    inp = I.load_inputs(cfg)
    geo = inp["geo"].set_index("geoid")
    v24 = inp["v24"].set_index("geoid")
    m0 = 100.0 * (v24.votes_d - v24.votes_r) / (v24.votes_d + v24.votes_r)
    n_group = ei.pivot_table(index="geoid", columns="group", values="n_group", aggfunc="first")[GROUPS]
    n_group = n_group.reindex(n_group.index.intersection(geo.index))
    state_of = geo.state_po.reindex(n_group.index)

    pres = {y: pd.read_csv(bt / f"pres_state_{y}.csv") for y in (2016, 2020)}
    v22 = T.midterm_totals(pd.read_csv(bt / "2022" / "senate_truth.csv"))
    v18 = T.midterm_totals(pd.read_csv(bt / "2018" / "senate_truth.csv"))
    states = sorted(state_of.unique())
    rho = T.rho_state(v22, T.pres_totals(pres[2020]), v18, T.pres_totals(pres[2016]), states,
                      cfg.turnout.rho_weights)
    nat = json.loads((OUTPUT / "national_swing.json").read_text(encoding="utf-8"))
    v24_state = n_group.sum(axis=1).groupby(state_of).sum()
    t_state = T.state_turnout_totals(v24_state, rho.rho, float(nat["s_nat"]), cfg.turnout.environment_beta)

    ev_p = proc / "early_vote_weights.parquet"
    omega_ev = (pd.read_parquet(ev_p).pivot(index="geoid", columns="group", values="omega_ev")[GROUPS]
                if ev_p.exists() else None)
    table, t_comp = T.build_turnout(n_group, m0, state_of, t_state, cfg, omega_ev)
    comp = pd.DataFrame({"state_po": t_comp.index, "T": t_comp.to_numpy(), "turnout_2026": t_state.reindex(t_comp.index).to_numpy(),
                         "votes_2024": v24_state.reindex(t_comp.index).to_numpy(),
                         "rho": rho.rho.reindex(t_comp.index).to_numpy(),
                         "rho_source": rho.rho_source.reindex(t_comp.index).to_numpy()})
    if write:
        OUTPUT.mkdir(exist_ok=True)
        write_parquet(stamp(table, "turnout:model", "phase5-0", "ok"), proc / "turnout.parquet")
        comp.to_csv(OUTPUT / "turnout_component.csv", index=False)
    return comp
