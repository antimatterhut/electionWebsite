"""Demographic crosstabs: manual curation first, pdfplumber helper for extraction (plan §4.4)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import load_config
from ._base import log, manual_dir, processed_dir, stamp, write_parquet

COLUMNS = ["poll_id", "geography", "group_dim", "group_value", "n_group", "dside_pct", "rside_pct", "margin_2p"]


def extract_pdf_tables(pdf_path: str | Path) -> list[pd.DataFrame]:
    """Helper only: raw tables from a poll PDF for the maintainer to review and copy into crosstabs.csv."""
    import pdfplumber

    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for tbl in page.extract_tables():
                if tbl and len(tbl) > 1:
                    out.append(pd.DataFrame(tbl[1:], columns=tbl[0]))
    return out


def clean_crosstabs(df: pd.DataFrame, group_map: pd.DataFrame | None, min_n: int) -> pd.DataFrame:
    """Harmonise labels via group_map.csv, derive n_group and margin_2p, drop cells with n_group < min_n."""
    d = df.copy()
    if group_map is not None and len(group_map):
        m = dict(zip(group_map.poll_label, group_map.canonical, strict=True))
        d["group_value"] = d.group_value.replace(m)
    if "n_group" not in d or d["n_group"].isna().any():
        base = d.get("n_group", pd.Series(index=d.index, dtype=float))
        d["n_group"] = base.fillna(d.get("n", 0) * d.get("pop_share", 0))
    d["margin_2p"] = 100.0 * (d.dside_pct - d.rside_pct) / (d.dside_pct + d.rside_pct)
    before = len(d)
    d = d[d.n_group >= min_n]
    if len(d) < before:
        log.info("crosstab_cells_dropped", dropped=before - len(d), min_n=min_n)
    return d[COLUMNS].reset_index(drop=True)


def ingest_crosstabs() -> pd.DataFrame:
    """Load data/manual/crosstabs.csv (hand-entered; no automated scraping of paywalled sources)."""
    cfg = load_config()
    raw = pd.read_csv(manual_dir() / "crosstabs.csv")
    gm_path = manual_dir() / "group_map.csv"
    gm = pd.read_csv(gm_path) if gm_path.exists() else None
    df = stamp(clean_crosstabs(raw, gm, cfg.crosstab.min_n), "manual:crosstabs.csv", "manual", "manual")
    write_parquet(df, processed_dir() / "crosstabs.parquet")
    return df
