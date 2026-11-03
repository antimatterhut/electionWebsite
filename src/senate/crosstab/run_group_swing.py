"""Stage `crosstab`: crosstabs + EI baselines -> processed/group_swing.parquet and gradients.json (plan §6.7)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import structlog

from ..config import ROOT, Settings, load_config
from ..ei import inputs as I
from ..ei.groups import _STATE_REGION, GROUPS
from ..ingest._base import processed_dir, stamp, write_parquet
from ..county.construct import regional_weights
from ..ei.shift_ei import group_pattern
from .harmonize import age_gradient, baseline_table, harmonize
from .hier_model import fit_group_swings

log = structlog.get_logger()
OUTPUT = ROOT / "output"


def _geo_region_weights(ei: pd.DataFrame, geo: pd.DataFrame) -> dict[str, dict[str, float]]:
    d = ei.merge(geo[["geoid", "state_po", "region"]], on="geoid")
    t = d.groupby(["state_po", "region"]).n_group.sum()
    out = {}
    for st, s in t.groupby(level=0):
        s = s.droplevel(0)
        out[st] = (s / s.sum()).to_dict()
    return out


def run_group_swing(cfg: Settings | None = None, s_nat: float | None = None,
                    state_swing: pd.DataFrame | None = None) -> pd.DataFrame:
    """Harmonise cells, fit the hierarchical model once nationally, write group_swing.parquet / gradients.json.

    Needs processed/ei_group_vote.parquet (stage `ei`). Without crosstab cells the output is the prior-only
    pattern (delta = S_nat + lambda * persisted EI pattern, shrinkage_factor 1, n_polls 0)."""
    cfg = cfg or load_config()
    proc = processed_dir()
    ei = pd.read_parquet(proc / "ei_group_vote.parquet")
    inp = I.load_inputs(cfg)
    geo = inp["geo"]
    if s_nat is None:
        s_nat = float(json.loads((OUTPUT / "national_swing.json").read_text())["s_nat"])
    cx_p = proc / "crosstabs.parquet"
    cx = pd.read_parquet(cx_p) if cx_p.exists() else pd.DataFrame()
    regions = sorted(geo.region.unique())
    reg_w = regional_weights(
        ei.pivot(index="geoid", columns="group", values="n_group")[GROUPS], geo.set_index("geoid").region)
    base = {lvl: baseline_table(ei, geo, lvl) for lvl in ("national", "region", "state")}
    gw = (ei.merge(geo[["geoid", "state_po", "region"]], on="geoid")
          .pipe(lambda d: pd.concat([
              d.assign(geography="national").groupby(["geography", "group"], observed=True).n_group.sum().reset_index(),
              d.assign(geography=d.region).groupby(["geography", "group"], observed=True).n_group.sum().reset_index(),
              d.assign(geography=d.state_po).groupby(["geography", "group"], observed=True).n_group.sum().reset_index(),
          ])).rename(columns={"n_group": "w"}))
    cells, age_cells = harmonize(cx, base, gw, cfg.crosstab.deff, cfg.crosstab.min_n) if len(cx) else (
        pd.DataFrame(columns=["poll_id", "geography", "group", "z", "var"]), pd.DataFrame())
    shift_p = proc / "ei_shift_2024.parquet"
    if shift_p.exists():
        pattern = group_pattern(pd.read_parquet(shift_p), reg_w)
        # region-free a_g prior mean: regional-weight average of the pattern
        wts = reg_w.reindex(pattern.index)
        pattern_g = (pattern * wts).sum() / wts.sum()
    else:
        log.warning("warning", code="NO_SHIFT_EI", note="ei_shift_2024.parquet missing: pattern prior = 0")
        pattern_g = pd.Series(0.0, index=GROUPS)
    from .hier_model import cell_weights

    W = cell_weights(cells, reg_w, regions, _geo_region_weights(ei, geo)) if len(cells) else np.zeros((0, len(regions)))
    offset = None
    if len(cells) and state_swing is not None:
        ss = state_swing.set_index("state_po").swing
        offset = np.array([float(ss.get(c, s_nat)) - s_nat if c in _STATE_REGION else 0.0 for c in cells.geography])
    gs = fit_group_swings(cells, GROUPS, regions, pattern_g, s_nat, W, cfg, offset)
    ag = age_gradient(age_cells, _age_baseline(), sd_young_share=_sd_young(inp["age"]))
    out = stamp(gs, "crosstab:hier_model", "phase3-0", "ok" if len(cells) else "manual")
    write_parquet(out, proc / "group_swing.parquet")
    (proc / "gradients.json").write_text(json.dumps({**ag, "gender_gradient": 0.0}, indent=2))
    return out


def _age_baseline() -> pd.DataFrame | None:
    v = I.load_validated()
    if v is None or v.empty:
        return None
    a = v[(v.group_dim == "age") & (v.year == 2024) & (v.geography == "national")]
    return a.groupby("group_value", as_index=False).d_share_2p.mean() if len(a) else None


def _sd_young(age: pd.DataFrame | None) -> float:
    if age is None or age.empty:
        return 0.05
    p = age.pivot(index="geoid", columns="age_bin", values="cvap_share")
    return float((p["18-29"] + p["30-44"]).std(ddof=0))
