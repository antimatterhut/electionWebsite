"""Demographic prior: national group swings applied to each state's electorate (cross-state borrowing).

Without it, an unpolled state's prior is the plain national swing S_nat, as if every state's electorate were the same
mix. The county layer already models "Hispanic voters swung X pts more than the average voter" (group_swing.parquet,
region x group deltas, plus the area-type term). Here the same deltas are aggregated to the state level for every
county in the country:

    raw_i = sum_g share_ig delta_{g,r(i)} + k_urban * delta_class(i)
    D_s   = (vote-weighted mean of raw_i over state s) - (vote-weighted mean over the nation)

D_s is the state's demographically implied deviation from the national swing. It is centered nationally, so it adds
nothing to the national environment, only moves it between states. The state prior becomes
S_nat + kappa * D_s (+ incumbency), and polls update it as before. Within a state the county tilt is still centered
on the state swing, so counties are unchanged apart from the new state level.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import structlog

from ..config import ROOT, Settings
from ..geo.fips import FIPS_STATE
from ..ingest._base import processed_dir

log = structlog.get_logger()
OUTPUT = ROOT / "output"


def state_deviation(omega: pd.DataFrame, state_of: pd.Series, region: pd.Series, delta: pd.DataFrame,
                    area_class: pd.Series | None = None, area_delta: dict[str, float] | None = None,
                    k_urban: float = 0.0) -> pd.DataFrame:
    """Per-state demographic deviation from the national swing.

    omega: county x group expected 2026 votes; state_of / region / area_class: per county (index geoid);
    delta: region x group swing means. Counties whose region has no delta row are dropped. Returns state_po, raw,
    D, votes (expected votes used as weights)."""
    g = list(omega.columns)
    share = omega.div(omega.sum(axis=1), axis=0)
    dc = delta.reindex(columns=g).reindex(region.reindex(omega.index).to_numpy()).to_numpy()
    raw = pd.Series((share.to_numpy() * dc).sum(axis=1), index=omega.index)
    ok = ~np.isnan(dc).any(axis=1)
    if area_class is not None and area_delta and k_urban:
        ad = area_class.reindex(omega.index).map(area_delta).astype(float)
        ad = ad.fillna(float(np.nanmean(list(area_delta.values()))))
        raw = raw + k_urban * ad
    w = omega.sum(axis=1)
    d = pd.DataFrame({"state_po": state_of.reindex(omega.index), "raw": raw, "w": w})[ok]
    nat = float(np.average(d.raw, weights=d.w))
    s = d.groupby("state_po").apply(lambda x: pd.Series({"raw": np.average(x.raw, weights=x.w), "votes": x.w.sum()}),
                                    include_groups=False)
    s["D"] = s.raw - nat
    return s.reset_index()


def build(cfg: Settings, write: bool = True) -> pd.DataFrame | None:
    """D_s for all 50 states from processed group_swing / area_swing and national CVAP. None when the group-swing
    stage has not run (then the model falls back to the plain national prior)."""
    from ..county.construct import omega_groups
    from ..county.urban import classify
    from ..ei import inputs as I
    from ..ei.groups import GROUPS

    proc = processed_dir()
    gs_p = proc / "group_swing.parquet"
    if not gs_p.exists():
        log.warning("warning", code="DEMO_PRIOR_NO_GROUP_SWING")
        return None
    delta = pd.read_parquet(gs_p).pivot(index="region", columns="group", values="delta_mean")[GROUPS]
    # AK has no usable county layer (district rows dropped, see ei/inputs.load_votes): it keeps D = 0.
    inp = I.load_inputs(cfg, states=sorted(set(FIPS_STATE.values()) - {"DC", "AK"}))
    geo = inp["geo"].set_index("geoid")
    gt = I.build_group_table(inp, cfg)
    gt["state_po"] = gt.geoid.map(geo.state_po)
    omega = omega_groups(gt[["geoid", "state_po", "group", "n_group"]].astype({"group": str}),
                         cfg.turnout.dropoff, GROUPS)
    area_p = proc / "area_swing.json"
    area = {k: v["delta"] for k, v in json.loads(area_p.read_text()).items()} if area_p.exists() else {}
    nchs_p = ROOT / "data" / "manual" / "nchs_urcs_2023.csv"
    classes, _ = classify(omega.index, inp["cvap"].groupby("geoid").cvap.sum(),
                          pd.read_csv(nchs_p) if nchs_p.exists() else None)
    out = state_deviation(omega, geo.state_po, geo.region, delta, classes, area, cfg.county.overlap_shrink.urban)
    if write:
        OUTPUT.mkdir(exist_ok=True)
        out.to_csv(OUTPUT / "demographic_prior.csv", index=False)
    log.info("demographic_prior", n_states=len(out), d_min=round(out.D.min(), 2), d_max=round(out.D.max(), 2))
    return out
