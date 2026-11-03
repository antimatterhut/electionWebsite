"""Stage `county`: EI + group swings + state swings -> calibrated county swings (plan §6.8, §6.11)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import structlog

from ..config import ROOT, Settings, load_config
from ..ei import inputs as I
from ..ei.groups import GROUPS
from ..ingest._base import processed_dir, stamp, write_parquet
from .construct import EI_OK, build_state, omega_groups, regional_weights

log = structlog.get_logger()
OUTPUT = ROOT / "output"


def _z_age(age: pd.DataFrame | None, index: pd.Index) -> pd.Series | None:
    """Standardised share of 18-44 voters (county age term, plan §6.8)."""
    if age is None or age.empty:
        return None
    p = age.pivot(index="geoid", columns="age_bin", values="cvap_share").reindex(index)
    young = (p["18-29"] + p["30-44"]).fillna((p["18-29"] + p["30-44"]).mean())
    return (young - young.mean()) / (young.std(ddof=0) or 1.0)


def run_county(cfg: Settings | None = None, state_swing: pd.DataFrame | None = None, write: bool = True
               ) -> pd.DataFrame:
    """Calibrated county projection table (swing/margin; T and E components enter via omega in later phases).

    state_swing: state_po, swing (default output/state_swing_2026.csv from `make model`)."""
    cfg = cfg or load_config()
    proc = processed_dir()
    ei = pd.read_parquet(proc / "ei_group_vote.parquet")
    gs_p = proc / "group_swing.parquet"
    gs = pd.read_parquet(gs_p) if gs_p.exists() else None
    if state_swing is None:
        state_swing = pd.read_csv(OUTPUT / "state_swing_2026.csv")
    ss = state_swing.drop_duplicates("state_po").set_index("state_po").swing if "state_po" in state_swing else None
    if ss is None:
        ss = state_swing.set_index("contest").swing
    inp = I.load_inputs(cfg)
    geo = inp["geo"].set_index("geoid")
    v24 = inp["v24"].set_index("geoid")
    m0 = 100.0 * (v24.votes_d - v24.votes_r) / (v24.votes_d + v24.votes_r)
    grad_p = proc / "gradients.json"
    beta_age = float(json.loads(grad_p.read_text()).get("age_gradient_per_sd", 0.0)) if grad_p.exists() else 0.0
    z_age = _z_age(inp["age"], geo.index)

    eig = ei.copy()
    eig["state_po"] = eig.geoid.map(geo.state_po)
    omega = omega_groups(eig[["geoid", "state_po", "group", "n_group"]].astype({"group": str}),
                         cfg.turnout.dropoff, GROUPS)
    ev_p = proc / "early_vote_weights.parquet"
    if ev_p.exists():  # Phase 4: calibrate with the final weights (omega^EV), plan §6.8
        ev = pd.read_parquet(ev_p).pivot(index="geoid", columns="group", values="omega_ev")[GROUPS]
        omega = ev.combine_first(omega).reindex(omega.index)
    reg_w = regional_weights(omega, geo.region)
    delta = None
    if gs is not None:
        delta = gs.pivot(index="region", columns="group", values="delta_mean")[GROUPS]
    status = (ei.groupby(eig.state_po, observed=True).ei_status
              .agg(lambda s: "fallback" if (s == "fallback").any() else "ok"))
    parts = []
    for st in sorted(geo.state_po.unique()):
        if st not in ss.index:
            continue
        ids = geo.index[(geo.state_po == st) & geo.index.isin(omega.index)]
        if len(ids) == 0:
            log.warning("warning", code="NO_EI_COUNTIES", state=st)
            continue
        counties = pd.DataFrame({"m0": m0.reindex(ids), "region": geo.region.reindex(ids)})
        parts.append(build_state(st, float(ss[st]), counties, omega.reindex(ids), delta, reg_w,
                                 str(status.get(st, "fallback")), z_age, beta_age, cfg.county.max_tilt))
    out = pd.concat(parts, ignore_index=True)
    out["region"] = out.geoid.map(geo.region)
    if write:
        write_parquet(stamp(out, "county:construct", "phase3-0", "ok"), proc / "county_swing_2026.parquet")
        OUTPUT.mkdir(exist_ok=True)
        out.to_csv(OUTPUT / "county_swing_2026.csv", index=False)
        write_calibration_report(out, ss)
    return out


def write_calibration_report(out: pd.DataFrame, ss: pd.Series) -> pd.DataFrame:
    """Per-state check: nu-weighted county swing equals S_s within 1e-6 (plan §7.4 first row)."""
    rows = []
    for st, g in out.groupby("state_po"):
        nu = g.omega / g.omega.sum()
        rows.append({"state_po": st, "S_s": float(ss[st]), "weighted_mean_county_swing": float((nu * g.s).sum()),
                     "abs_err": abs(float((nu * g.s).sum()) - float(ss[st])), "county_method": g.county_method.iloc[0],
                     "lambda": float(g.lam.iloc[0]), "n_counties": len(g), "max_abs_tilt": float(g.tilt.abs().max())})
    rep = pd.DataFrame(rows)
    d = OUTPUT / "county"
    d.mkdir(parents=True, exist_ok=True)
    rep.to_csv(d / "calibration_check.csv", index=False)
    return rep
