"""Census CVAP special tabulation + ACS education/age shares by county (plan §4.5)."""
from __future__ import annotations

import io
import json
import math
import os
import zipfile

import pandas as pd

from ..geo.fips import pad_county
from ..io import Fetcher
from ._base import log, manual_dir, processed_dir, stamp, write_parquet

# URL/availability of 2019-2023 CVAP is unverified (plan A8); fallback vintage is 2018-2022.
CVAP_URLS = [
    "https://www2.census.gov/programs-surveys/decennial/rdo/datasets/2023/2023-cvap/CVAP_2019-2023_ACS_csv_files.zip",
    "https://www2.census.gov/programs-surveys/decennial/rdo/datasets/2022/2022-cvap/CVAP_2018-2022_ACS_csv_files.zip",
]
ACS_URL = "https://api.census.gov/data/{year}/acs/acs5"

_RACE_MAP = {
    "White Alone": "wnh", "Black or African American Alone": "black",
    "Hispanic or Latino": "hisp", "Asian Alone": "asian",
}
RACES = ["wnh", "black", "hisp", "asian", "other"]
AGE_VARS = {
    "18-29": [f"B01001_{i:03d}" for i in (7, 8, 9, 10, 11, 31, 32, 33, 34, 35)],
    "30-44": [f"B01001_{i:03d}" for i in (12, 13, 14, 36, 37, 38)],
    "45-64": [f"B01001_{i:03d}" for i in (15, 16, 17, 18, 19, 39, 40, 41, 42, 43)],
    "65+": [f"B01001_{i:03d}" for i in (20, 21, 22, 23, 24, 25, 44, 45, 46, 47, 48, 49)],
}


def parse_cvap_county(raw: pd.DataFrame) -> pd.DataFrame:
    """Census County.csv (geoname, lntitle, geoid, cvap_est, cvap_moe) -> geoid, race5, cvap, moe."""
    df = raw.copy()
    df.columns = [c.lower() for c in df.columns]
    df["geoid"] = df["geoid"].astype(str).str[-5:]
    df["cvap_est"] = pd.to_numeric(df.cvap_est)
    df["cvap_moe"] = pd.to_numeric(df.cvap_moe)
    tot = df[df.lntitle == "Total"].set_index("geoid")[["cvap_est", "cvap_moe"]]
    rows = []
    for title, race in _RACE_MAP.items():
        part = df[df.lntitle == title].set_index("geoid")[["cvap_est", "cvap_moe"]].reindex(tot.index).fillna(0)
        rows.append(part.assign(race5=race))
    known = pd.concat(rows)
    kn_sum = known.groupby(level=0).cvap_est.sum()
    kn_moe = known.groupby(level=0).cvap_moe.apply(lambda s: math.sqrt((s**2).sum()))
    other = pd.DataFrame({
        "cvap_est": (tot.cvap_est - kn_sum).clip(lower=0),
        "cvap_moe": (tot.cvap_moe**2 + kn_moe**2) ** 0.5,
        "race5": "other",
    })
    out = pd.concat(rows + [other]).reset_index().rename(columns={"index": "geoid"})
    out = out.rename(columns={"cvap_est": "cvap", "cvap_moe": "moe"})
    out = out[(out.geoid != "11001") & (out.geoid.str[:2].astype(int) <= 56)]  # no DC/PR: no Senate race
    out["cvap"] = out.cvap.round().astype("int32")
    out["moe"] = out.moe.astype(float)
    return out[["geoid", "race5", "cvap", "moe"]].sort_values(["geoid", "race5"]).reset_index(drop=True)


def _fetch_cvap(fetcher: Fetcher) -> tuple[pd.DataFrame, str]:
    last: Exception | None = None
    for url in CVAP_URLS:
        try:
            body = fetcher.get(url, "census_cvap")
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                name = next(n for n in z.namelist() if n.lower().endswith("county.csv"))
                raw = pd.read_csv(z.open(name), encoding="latin-1", dtype=str)
            return parse_cvap_county(raw), url.rsplit("/", 1)[-1]
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"CVAP download failed: {last}")


def _acs(fetcher: Fetcher, year: int, variables: list[str]) -> pd.DataFrame:
    key = os.environ.get("CENSUS_API_KEY")
    if not key:
        raise RuntimeError("CENSUS_API_KEY not set (free key: https://api.census.gov/data/key_signup.html)")
    params = {"get": ",".join(variables), "for": "county:*", "key": key}
    data = json.loads(fetcher.get(ACS_URL.format(year=year), "census_acs", params=params))
    df = pd.DataFrame(data[1:], columns=data[0])
    df["geoid"] = df["state"] + df["county"]
    df = df.drop(columns=["state", "county"])
    for v in variables:
        df[v] = pd.to_numeric(df[v])
    return df


def _acs_age(fetcher: Fetcher, year: int) -> pd.DataFrame:
    variables = [v for vs in AGE_VARS.values() for v in vs]
    acs = _acs(fetcher, year, [v + "E" for v in variables])
    return acs.rename(columns={v + "E": v for v in variables})


def age_shares(acs: pd.DataFrame) -> pd.DataFrame:
    """Adult-population age-bin shares (proxy for CVAP age shares; ACS has no joint CVAP age table)."""
    bins = pd.DataFrame({b: acs[v].sum(axis=1) for b, v in AGE_VARS.items()})
    bins.index = acs.index
    bins = bins.div(bins.sum(axis=1), axis=0)
    bins["geoid"] = acs["geoid"].values
    out = bins.melt(id_vars="geoid", var_name="age_bin", value_name="cvap_share")
    return out.sort_values(["geoid", "age_bin"]).reset_index(drop=True)


def college_share_wnh(acs: pd.DataFrame) -> pd.DataFrame:
    """Bachelor's+ share of white-non-Hispanic adults 25+ (C15002H: bachelor's+ are _006 and _011)."""
    share = (acs["C15002H_006E"] + acs["C15002H_011E"]) / acs["C15002H_001E"].where(acs["C15002H_001E"] > 0)
    return pd.DataFrame({"geoid": acs["geoid"], "college_share_wnh": share.astype(float)})


def ingest_acs_cvap(fetcher: Fetcher | None = None, acs_year: int = 2023, allow_fallback: bool = True
                    ) -> dict[str, pd.DataFrame]:
    """Write cvap_county / edu_county / age_county parquet. Each falls back independently to data/manual."""
    own = fetcher is None
    fetcher = fetcher or Fetcher()
    out: dict[str, pd.DataFrame] = {}
    try:
        def attempt(name, fn, version):
            try:
                df = stamp(fn(), name, version)
            except Exception as e:  # noqa: BLE001
                if not allow_fallback:
                    raise
                log.warning("warning", code="FALLBACK_USED", source=name, fallback="manual", error=str(e)[:200])
                mp = manual_dir() / f"{name}.csv"
                if not mp.exists():
                    raise RuntimeError(f"{name}: fetch failed ({e}) and no manual fallback at {mp}") from e
                df = pd.read_csv(mp, dtype={"geoid": str})
                df = stamp(df, f"manual:{name}", "manual", "manual")
            out[name] = df
            write_parquet(df, processed_dir() / f"{name}.parquet")

        version_holder = {}

        def cvap():
            df, version_holder["v"] = _fetch_cvap(fetcher)
            return df

        attempt("cvap_county", cvap, "census_cvap")
        attempt("edu_county", lambda: college_share_wnh(_acs(fetcher, acs_year, ["C15002H_001E", "C15002H_006E",
                                                                                   "C15002H_011E"])), f"acs5_{acs_year}")
        attempt("age_county", lambda: age_shares(_acs_age(fetcher, acs_year)), f"acs5_{acs_year}")
        for k in ("cvap_county", "edu_county", "age_county"):
            out[k]["geoid"] = pad_county(out[k]["geoid"])
        return out
    finally:
        if own:
            fetcher.close()
