"""EI vs validated-voter benchmarks (plan §7.3): output/validation/ei_flags.csv."""
from __future__ import annotations

import pandas as pd

from ..config import ROOT, Settings, load_config
from ..ingest._base import processed_dir

OUTPUT = ROOT / "output" / "validation"
COLUMNS = ["group", "region", "ei", "benchmark", "diff", "study", "flag"]
LARGE_GROUP_SHARE = 0.10  # groups >= 10% of CVAP are held to the hard 12-pt limit


def ei_group_shares(ei: pd.DataFrame, geo: pd.DataFrame) -> pd.DataFrame:
    """n-weighted EI two-party D share by (region, group) plus 'national'; also each group's vote share."""
    d = ei.merge(geo[["geoid", "region"]], on="geoid")
    d["wt"] = d.theta_mean * d.n_group
    by_r = d.groupby(["region", "group"], observed=True).agg(wt=("wt", "sum"), n=("n_group", "sum")).reset_index()
    nat = d.groupby("group", observed=True).agg(wt=("wt", "sum"), n=("n_group", "sum")).reset_index()
    nat["region"] = "national"
    t = pd.concat([nat, by_r], ignore_index=True)
    t["ei"] = t.wt / t.n
    tot = t.groupby("region").n.transform("sum")
    t["share"] = t.n / tot
    return t[["region", "group", "ei", "share"]]


def compare(ei: pd.DataFrame, geo: pd.DataFrame, validated: pd.DataFrame | None, cfg: Settings
            ) -> tuple[pd.DataFrame, list[str]]:
    """Rows for every 2024 validated-voter benchmark that matches an EI group; returns (table, hard failures)."""
    if validated is None or validated.empty:
        return pd.DataFrame(columns=COLUMNS), []
    sh = ei_group_shares(ei, geo)
    v = validated[(validated.year == 2024) & validated.group_value.isin(sh.group.unique())].copy()
    v["region"] = v.geography
    m = v.merge(sh, left_on=["region", "group_value"], right_on=["region", "group"], how="inner")
    out = pd.DataFrame({"group": m.group_value, "region": m.region, "ei": m.ei, "benchmark": m.d_share_2p,
                        "diff": 100 * (m.ei - m.d_share_2p), "study": m.study})
    out["flag"] = out["diff"].abs() > cfg.validation.ei_flag_pts
    big = out["diff"].abs() > cfg.validation.ei_fail_pts
    fails = sorted(set((out.group + "@" + out.region)[big & (m.share.to_numpy() >= LARGE_GROUP_SHARE)]))
    return out[COLUMNS], fails


def write_flags(ei: pd.DataFrame, geo: pd.DataFrame, validated: pd.DataFrame | None, cfg: Settings | None = None
                ) -> tuple[pd.DataFrame, list[str]]:
    cfg = cfg or load_config()
    tbl, fails = compare(ei, geo, validated, cfg)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    tbl.to_csv(OUTPUT / "ei_flags.csv", index=False)
    return tbl, fails


def run_validation(cfg: Settings | None = None) -> tuple[pd.DataFrame, list[str]]:
    from . import inputs as I

    cfg = cfg or load_config()
    ei = pd.read_parquet(processed_dir() / "ei_group_vote.parquet")
    inp = I.load_inputs(cfg)
    return write_flags(ei, inp["geo"], I.load_validated(), cfg)
