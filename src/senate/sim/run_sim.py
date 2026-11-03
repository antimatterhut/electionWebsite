"""Stage `sim`: state/county simulation from the final projection (plan §6.12, §8.1).

Inputs: output/summary.json + output/state_swing_2026.csv (`make model`), and optionally
processed/county_swing_2026.parquet (`make county`), processed/turnout.parquet (`make turnout`). Without a county
layer the simulation runs at state level and says so in sim_summary.json (`county_layer: false`)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import structlog

from ..config import ROOT, Settings, load_config
from ..ei.groups import GROUPS, REGIONS
from ..export.to_json import add_simulation, write_summary
from ..export.validate_rollup import check_rollup
from ..geo.fips import FIPS_STATE
from ..ingest._base import manual_dir, processed_dir
from . import covariance as C
from . import errors as E
from . import outputs as O
from . import simulate as S

log = structlog.get_logger()
OUTPUT = ROOT / "output"


def build_inputs(states: pd.DataFrame, em: E.ErrorModel, cfg: Settings, cvap: pd.DataFrame | None = None,
                 counties: pd.DataFrame | None = None, group_w: pd.DataFrame | None = None) -> S.SimInputs:
    """states: index contest, columns m_hat, polled, n_eff, state_po. counties (optional): geoid, state_po, region,
    m_hat, omega (final expected votes); the unit of a county is its state_po."""
    units = states.copy()
    units["sd_state"] = S.state_sd(units.polled, units.n_eff, em, cfg.polls.sigma_poll)
    cty = None
    if counties is not None and len(counties):
        cty = counties.rename(columns={"state_po": "unit"}).copy()
        cty["votes"] = cty.omega
        cty["nu"] = cty.omega / cty.groupby("unit").omega.transform("sum")
        cty = cty[cty.unit.isin(units.index)]
        units.loc[units.index.isin(cty.unit), "m_hat"] = (cty.m_hat * cty.nu).groupby(cty.unit).sum()
    coarse = pd.Series({u: E.region_of(p) for u, p in units.state_po.items()})
    rs = S.region_shares(units.index, cty, coarse)
    if group_w is None:
        group_w = pd.DataFrame(1.0 / len(GROUPS), index=units.index, columns=GROUPS)
    gw = group_w.reindex(units.index).fillna(1.0 / len(GROUPS))
    if cvap is not None and len(cvap):
        comp = C.state_composition(cvap, cvap.geoid.str[:2].map(FIPS_STATE))
        comp = comp.reindex(units.state_po.unique()).fillna(0.0)
        arr = (C.cosine_similarity(comp).reindex(index=units.state_po, columns=units.state_po).fillna(0.0)
               .to_numpy(copy=True))
        np.fill_diagonal(arr, 1.0)
        sim = pd.DataFrame(arr, index=units.index, columns=units.index)
    else:
        sim = pd.DataFrame(np.eye(len(units)), index=units.index, columns=units.index)
    corr = C.state_correlation(sim, cfg.sim.rho.state_similarity, list(units.state_po))
    return S.SimInputs(units, rs, gw, corr, cty)


def _group_weights(proc, states: pd.Index) -> pd.DataFrame | None:
    p = proc / "turnout.parquet"
    if not p.exists():
        return None
    t = pd.read_parquet(p)
    w = t.pivot_table(index="state_po", columns="group", values="omega_ev", aggfunc="sum")[GROUPS]
    return w.div(w.sum(axis=1), axis=0).reindex(states)


def run_sim(cfg: Settings | None = None, write: bool = True, n_draws: int | None = None) -> dict:
    cfg = cfg or load_config()
    proc = processed_dir()
    summary = json.loads((OUTPUT / "summary.json").read_text(encoding="utf-8"))
    races = pd.read_csv(manual_dir() / "races_2026.csv", dtype=str, keep_default_na=False)
    sw = pd.read_csv(OUTPUT / "state_swing_2026.csv").drop_duplicates("state_po").set_index("state_po")
    proj = {r["state"]: r for r in summary["races"]}
    st = pd.DataFrame({"m_hat": {s: r["proj_margin"] for s, r in proj.items()}}).join(sw[["polled", "n_eff"]])
    st["state_po"] = st.index
    st["polled"] = st.polled.fillna(False)
    st["n_eff"] = st.n_eff.fillna(0.0)

    cvap_p = proc / "cvap_county.parquet"
    cvap = pd.read_parquet(cvap_p) if cvap_p.exists() else None
    counties, rollup_err = _load_counties(proc, st, sw, summary)

    miss_p = manual_dir() / "historical_midterm_polling_misses.csv"
    misses = pd.read_csv(miss_p) if miss_p.exists() else pd.DataFrame()
    em = E.fit_error_model(misses, cfg)
    resid_p = OUTPUT / "county" / "backtest_residuals.csv"  # optional; produced by a county backtest with weights
    if resid_p.exists():
        em.county, src = E.county_sd_from_residuals(pd.read_csv(resid_p), em.county)
        em.notes.append(f"county sd source: {src}")
    inp = build_inputs(st, em, cfg, cvap, counties, _group_weights(proc, st.index))
    res = S.simulate(inp, em, n_draws or cfg.sim.n_draws, cfg.sim.seed, cfg.sim.rho.region_neighbor, cfg.sim.chunk)
    sim = O.summarize(res, races, cfg)
    sim["county_layer"] = counties is not None
    sim["rollup_excluded"] = rollup_err
    if write:
        O.write_outputs(res, sim, races, cfg, OUTPUT, em.as_dict())
        write_summary(add_simulation(summary, sim), OUTPUT / "summary.json")
    return {"sim": sim, "error_model": em, "result": res}


def _load_counties(proc, st: pd.DataFrame, sw: pd.DataFrame, summary: dict):
    """County table filtered to states whose roll-up identity holds; returns (counties | None, [excluded states])."""
    p = proc / "county_swing_2026.parquet"
    if not p.exists():
        return None, []
    cty = pd.read_parquet(p)
    comp = sw[["m0", "swing"]].copy()  # unrounded components (summary.json is rounded to 3 dp)
    for name, col, f in (("T", "T", "turnout_component.csv"), ("E", "E", "early_vote_component.csv")):
        fp = OUTPUT / f
        comp[name] = pd.read_csv(fp).set_index("state_po")[col].reindex(comp.index).fillna(0.0) if fp.exists() else 0.0
    comp.index.name = "state_po"
    bad = []
    for s, g in cty.groupby("state_po"):
        try:
            check_rollup(g, comp.reset_index())
        except AssertionError as e:
            log.warning("warning", code="ROLLUP_MISMATCH", state=s, detail=str(e)[:200])
            bad.append(s)
    return cty[~cty.state_po.isin(bad)], bad
