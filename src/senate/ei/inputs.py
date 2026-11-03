"""Assemble EI inputs: county votes, CVAP groups, covariates, regions, priors (plan §6.6)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import structlog

from ..config import ROOT, Settings
from ..geo.fips import FIPS_STATE
from ..ingest._base import manual_dir, processed_dir
from .groups import assign_regions, build_county_groups, cvap_wide

log = structlog.get_logger()

# Placeholder national two-party D shares by group (2024), used only where validated_voter_priors.csv is empty.
# Rounded from memory of the published Pew / AP VoteCast / Catalist 2024 tables - UNVERIFIED, replace by filling
# data/manual/validated_voter_priors.csv (plan §4.7). The wide SD (0.35 logit) keeps them weakly informative.
PLACEHOLDER_PRIOR = {"wnh_college": 0.52, "wnh_noncollege": 0.34, "black": 0.86, "hispanic": 0.46,
                     "asian": 0.58, "other": 0.50}
PLACEHOLDER_SD = 0.35
RAW = ROOT / "data" / "raw"


def load_votes(year: int) -> pd.DataFrame:
    """County two-party votes: geoid, state_po, votes_d, votes_r. Uses processed/pres_county.parquet when present
    (MEDSL), else the newest tonmcg raw county file. Alaska's state-house-district rows are dropped (the
    district->borough crosswalk is empty, so Alaska has no county layer yet)."""
    pc = processed_dir() / "pres_county.parquet"
    if pc.exists():
        d = pd.read_parquet(pc)
        d = d[d.year == year]
        if len(d):
            return d[["geoid", "state_po", "votes_d", "votes_r"]].reset_index(drop=True)
    files = sorted((RAW / f"tonmcg_{year}").glob(f"*/{year}_US_County_Level_Presidential_Results.csv"))
    if not files:
        raise FileNotFoundError(f"no county presidential results for {year}: fill pres_county or fetch tonmcg_{year}")
    d = pd.read_csv(files[-1], dtype={"county_fips": str})
    out = pd.DataFrame({"geoid": d.county_fips.str.zfill(5), "votes_d": d.votes_dem.astype(int),
                        "votes_r": d.votes_gop.astype(int)})
    out["state_po"] = out.geoid.str[:2].map(FIPS_STATE)
    out = out[(out.state_po.notna()) & (out.state_po != "DC") & (out.state_po != "AK")]
    return out.reset_index(drop=True)


def _z(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=0)
    return (s - s.mean()) / (sd if sd > 0 else 1.0)


def load_inputs(cfg: Settings, states: list[str] | None = None) -> dict:
    """Everything the EI runs need, restricted to the 2026 race states (or `states`)."""
    proc = processed_dir()
    races = pd.read_csv(manual_dir() / "races_2026.csv", dtype=str, keep_default_na=False)
    race_states = set(states or races.state_po)
    v24, v20 = load_votes(2024), load_votes(2020)
    cvap = pd.read_parquet(proc / "cvap_county.parquet")
    edu = pd.read_parquet(proc / "edu_county.parquet") if (proc / "edu_county.parquet").exists() else None
    age = pd.read_parquet(proc / "age_county.parquet") if (proc / "age_county.parquet").exists() else None
    wide = cvap_wide(cvap)
    keep = set(wide.index)
    v24 = v24[v24.state_po.isin(race_states) & v24.geoid.isin(keep) & ((v24.votes_d + v24.votes_r) > 0)]
    v20 = v20[v20.geoid.isin(set(v24.geoid)) & ((v20.votes_d + v20.votes_r) > 0)]
    v24 = v24[v24.geoid.isin(set(v20.geoid))].sort_values("geoid").reset_index(drop=True)
    v20 = v20.sort_values("geoid").reset_index(drop=True)
    w = wide.reindex(v24.geoid)
    geo = pd.DataFrame({"geoid": v24.geoid, "state_po": v24.state_po.values,
                        "region": assign_regions(v24.state_po.reset_index(drop=True), w.reset_index(drop=True)).values})
    # covariates (standardised); only the ones with data are used - see data_dictionary
    tot = w.sum(axis=1)
    cov = pd.DataFrame({"log_cvap": _z(np.log1p(tot))}, index=v24.geoid)
    if edu is not None:
        cov["college_wnh"] = _z(edu.drop_duplicates("geoid").set_index("geoid").college_share_wnh.reindex(cov.index)
                                .fillna(0.38))
    if age is not None:
        a = age.pivot(index="geoid", columns="age_bin", values="cvap_share").reindex(cov.index)
        cov["age65"] = _z(a["65+"].fillna(a["65+"].mean()))
    return {"v24": v24, "v20": v20, "cvap": cvap, "edu": edu, "age": age, "geo": geo, "cov": cov, "races": races}


def group_priors(priors: pd.DataFrame | None, groups: list[str], region: str | None = None,
                 state: str | None = None) -> pd.DataFrame:
    """Prior mean/SD per group: group, mu (prob), sd (logit), prior_level.

    Takes the mean of 2024 validated-voter studies at the most specific available geography (state > region >
    national); sd = max(0.20, SD of study means on the logit scale). Empty table -> documented placeholders."""
    rows = []
    for g in groups:
        pick = None
        if priors is not None and len(priors):
            p = priors[(priors.group_value == g) & (priors.year == 2024)]
            for level, key in (("state", state), ("region", region), ("national", "national")):
                q = p[p.geography == key] if key else p.iloc[0:0]
                if len(q):
                    m = q.d_share_2p.astype(float)
                    lg = np.log(m / (1 - m))
                    pick = (float(m.mean()), float(max(0.20, lg.std(ddof=0) if len(m) > 1 else 0.20)), level)
                    break
        rows.append({"group": g, "mu": pick[0] if pick else PLACEHOLDER_PRIOR[g],
                     "sd": pick[1] if pick else PLACEHOLDER_SD,
                     "prior_level": pick[2] if pick else "placeholder"})
    return pd.DataFrame(rows)


def load_validated() -> pd.DataFrame | None:
    p = processed_dir() / "validated_voter_priors.parquet"
    return pd.read_parquet(p) if p.exists() else None


def build_group_table(inp: dict, cfg: Settings, year: int = 2024) -> pd.DataFrame:
    v = inp["v24"] if year == 2024 else inp["v20"]
    return build_county_groups(v, inp["cvap"], inp["edu"], cfg.ei.relative_turnout, cfg.ei.groups)
