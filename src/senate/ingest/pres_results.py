"""2020/2024 presidential county results from MEDSL (plan §4.1)."""
from __future__ import annotations

import io
import json

import pandas as pd

from ..geo import crosswalks
from ..geo.fips import pad_county, state_po_from_geoid
from ..io import Fetcher
from ._base import log, manual_dir, processed_dir, stamp, write_parquet

# DOI verified against the Dataverse API on 2026-11-02 (title: County Presidential Election Returns 2000-2024).
MEDSL_DOI = "doi:10.7910/DVN/VOQCHQ"
YEARS = (2020, 2024)
NON_CANDIDATES = {"TOTAL VOTES CAST", "OVERVOTES", "UNDERVOTES"}


def clean_medsl(raw: pd.DataFrame) -> pd.DataFrame:
    """Plan §4.1 cleaning steps 1-4, 6, 7 on a MEDSL frame -> processed schema (without provenance)."""
    df = raw.copy()
    df.columns = [c.lower() for c in df.columns]
    df = df[(df.office.str.upper() == "US PRESIDENT") & (df.year.isin(YEARS))]
    df["county_fips"] = pad_county(df["county_fips"])
    df["party3"] = df.party.str.upper().map({"DEMOCRAT": "D", "DEMOCRATIC": "D", "REPUBLICAN": "R"}).fillna("OTHER")
    # 2024 MEDSL carries a TOTAL row alongside per-mode rows for many states (summing both double-counts). Where a
    # county has TOTAL rows keep only those; otherwise sum its modes. A missing mode is its own mode (ID, NC, UT ...
    # report mode-less rows), and the TX/WI/WV "TOTAL VOTES CAST" pseudo-candidate rows are not votes for anyone.
    df["mode_k"] = df["mode"].fillna("").str.upper().str.strip()
    has_total = df.mode_k.eq("TOTAL").groupby([df.year, df.county_fips]).transform("max").astype(bool)
    df = df[~has_total | df.mode_k.eq("TOTAL")]
    real = ~df.candidate.str.upper().isin(NON_CANDIDATES)
    cand = df[real].groupby(["year", "county_fips", "party3"], as_index=False).candidatevotes.sum()
    wide = cand.pivot_table(index=["year", "county_fips"], columns="party3", values="candidatevotes",
                            aggfunc="sum", fill_value=0).reset_index()
    for c in ("D", "R", "OTHER"):
        if c not in wide:
            wide[c] = 0
    # totalvotes repeats per candidate row: take it once per (year, county, mode) before summing modes
    tot = (df.groupby(["year", "county_fips", "mode_k"], as_index=False).totalvotes.max()
           .groupby(["year", "county_fips"], as_index=False).totalvotes.sum())
    out = wide.merge(tot, on=["year", "county_fips"], how="left")
    out = out.rename(columns={"county_fips": "geoid", "D": "votes_d", "R": "votes_r", "OTHER": "votes_other",
                              "totalvotes": "votes_total"})
    out["votes_total"] = out[["votes_total"]].join(out[["votes_d", "votes_r", "votes_other"]].sum(axis=1)
                                                   .rename("s")).max(axis=1)
    parts = []
    for y, g in out.groupby("year"):
        g = g.copy()
        g["geoid"] = crosswalks.apply_fips_aliases(g.geoid, int(y))
        g = g.groupby(["year", "geoid"], as_index=False)[["votes_d", "votes_r", "votes_other", "votes_total"]].sum()
        parts.append(g)
    out = pd.concat(parts, ignore_index=True)
    out = crosswalks.drop_non_senate_geographies(out)
    out["state_po"] = state_po_from_geoid(out.geoid)
    out["margin_2p"] = (100.0 * (out.votes_d - out.votes_r) / (out.votes_d + out.votes_r)).astype("float32")
    out["year"] = out.year.astype("int16")
    for c in ("votes_d", "votes_r", "votes_other", "votes_total"):
        out[c] = out[c].astype("int32")
    cols = ["year", "geoid", "state_po", "votes_d", "votes_r", "votes_other", "votes_total", "margin_2p"]
    return out[cols].sort_values(["year", "geoid"]).reset_index(drop=True)


DATASET_API = "https://dataverse.harvard.edu/api/datasets/:persistentId"
DATAFILE_API = "https://dataverse.harvard.edu/api/access/datafile/{id}"
DATAFILE_LABEL = "countypres_2000-2024.tab"


def _fetch(fetcher: Fetcher) -> pd.DataFrame:
    """Resolve the county file id from the dataset record (DOI confirmed 2026-11-02), then download it."""
    meta = json.loads(fetcher.get(DATASET_API, "medsl_meta", params={"persistentId": MEDSL_DOI}, archive=False))
    files = meta["data"]["latestVersion"]["files"]
    fid = next(f["dataFile"]["id"] for f in files if f["label"] == DATAFILE_LABEL)
    body = fetcher.get(DATAFILE_API.format(id=fid), "medsl")
    raw = pd.read_csv(io.BytesIO(body), sep="	", dtype=str)
    return clean_medsl(raw.astype({"year": int, "candidatevotes": float, "totalvotes": float}))


FULL_FILE_NAMES = ("countypres_2000-2024.csv", "countypres_2000-2024.tab")


def _read_manual() -> pd.DataFrame:
    """Manual fallback: pres_county_{2020,2024}.csv (plan §4.1), or the whole MEDSL file dropped into data/manual/
    (the Dataverse download needs a guestbook response, so it is fetched by hand)."""
    types = {"year": int, "candidatevotes": float, "totalvotes": float}
    frames = []
    for y in YEARS:
        p = manual_dir() / f"pres_county_{y}.csv"
        if p.exists():
            frames.append(pd.read_csv(p, dtype=str).astype(types))
    for name in FULL_FILE_NAMES:
        p = manual_dir() / name
        if p.exists():
            frames.append(pd.read_csv(p, sep=None, engine="python", dtype=str).astype(types))
    frames = [f for f in frames if len(f)]
    if not frames:
        raise FileNotFoundError(
            f"no manual presidential results in {manual_dir()}: fill pres_county_2020.csv / pres_county_2024.csv "
            f"or drop the MEDSL file ({FULL_FILE_NAMES[0]}) there")
    return stamp(clean_medsl(pd.concat(frames, ignore_index=True)), "manual:pres_county", "manual", "manual")


def ingest_pres_results(fetcher: Fetcher | None = None, allow_fallback: bool = True) -> pd.DataFrame:
    """Return processed/pres_county.parquet contents; falls back to data/manual/pres_county_{2020,2024}.csv
    (same raw MEDSL schema, run through the same cleaning)."""
    own = fetcher is None
    fetcher = fetcher or Fetcher()
    try:
        try:
            df = stamp(_fetch(fetcher), "medsl", MEDSL_DOI)
            log.info("source_fetch", source="pres_results", status="ok", rows=len(df), fallback=False)
        except Exception as e:  # noqa: BLE001
            if not allow_fallback:
                raise
            log.warning("warning", code="FALLBACK_USED", source="pres_results", fallback="manual", error=str(e)[:200])
            df = _read_manual()
            log.info("source_fetch", source="pres_results", status="fallback", rows=len(df), fallback=True)
        write_parquet(df, processed_dir() / "pres_county.parquet")
        return df
    finally:
        if own:
            fetcher.close()
