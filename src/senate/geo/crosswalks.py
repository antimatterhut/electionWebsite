"""Geography/vintage crosswalks (plan §2.2, §5.2). CSVs live in data/crosswalks/."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import ROOT
from .fips import DC_COUNTY

XW = ROOT / "data" / "crosswalks"


def load(name: str, xw_dir: Path = XW) -> pd.DataFrame:
    return pd.read_csv(xw_dir / name, dtype=str)


def apply_fips_aliases(geoid: pd.Series, year: int, xw_dir: Path = XW) -> pd.Series:
    """Map old/renamed county FIPS to the current code where valid_from <= year <= valid_to."""
    a = load("fips_aliases.csv", xw_dir)
    a = a[(a.valid_from.astype(int) <= year) & (a.valid_to.astype(int) >= year)]
    return geoid.replace(dict(zip(a.old_geoid, a.new_geoid, strict=True)))


def towns_to_counties(df: pd.DataFrame, value_cols: list[str], xw_dir: Path = XW) -> pd.DataFrame:
    """Sum town-level rows (column `town_geoid`) to counties; CT goes to planning regions instead."""
    t = load("town_to_county.csv", xw_dir)
    m = df.merge(t, on="town_geoid", how="left", validate="m:1")
    if m.county_geoid.isna().any():
        missing = m.loc[m.county_geoid.isna(), "town_geoid"].unique()[:5]
        raise ValueError(f"towns missing from town_to_county.csv, e.g. {list(missing)}")
    keys = [c for c in df.columns if c not in value_cols + ["town_geoid"]] + ["county_geoid"]
    return m.groupby(keys, as_index=False)[value_cols].sum().rename(columns={"county_geoid": "geoid"})


def ct_towns_to_planning_regions(df: pd.DataFrame, value_cols: list[str], xw_dir: Path = XW) -> pd.DataFrame:
    t = load("ct_town_to_planning_region.csv", xw_dir)
    m = df.merge(t, on="town_geoid", how="left", validate="m:1")
    if m.pr_geoid.isna().any():
        raise ValueError("CT towns missing from ct_town_to_planning_region.csv")
    keys = [c for c in df.columns if c not in value_cols + ["town_geoid"]] + ["pr_geoid"]
    return m.groupby(keys, as_index=False)[value_cols].sum().rename(columns={"pr_geoid": "geoid"})


def ak_districts_to_boroughs(df: pd.DataFrame, value_cols: list[str], xw_dir: Path = XW) -> pd.DataFrame:
    """Pop-weighted split of State House district results into boroughs/census areas."""
    t = load("ak_district_to_borough.csv", xw_dir)
    t["weight_pop"] = t.weight_pop.astype(float)
    m = df.merge(t, on="house_district", how="left", validate="m:m")
    if m.borough_geoid.isna().any():
        raise ValueError("AK districts missing from ak_district_to_borough.csv")
    for c in value_cols:
        m[c] = m[c] * m["weight_pop"]
    keys = [c for c in df.columns if c not in value_cols + ["house_district"]] + ["borough_geoid"]
    out = m.groupby(keys, as_index=False)[value_cols].sum().rename(columns={"borough_geoid": "geoid"})
    out[value_cols] = out[value_cols].round().astype("int64")
    return out


def drop_non_senate_geographies(df: pd.DataFrame, col: str = "geoid") -> pd.DataFrame:
    """Drop DC and territories (state FIPS > 56)."""
    return df[(df[col] != DC_COUNTY) & (df[col].str[:2].astype(int) <= 56)].copy()
