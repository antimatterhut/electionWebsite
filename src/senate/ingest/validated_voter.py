"""Validated-voter priors (Pew, AP VoteCast, Catalist summaries) - hand-entered tables (plan §4.7)."""
from __future__ import annotations

import pandas as pd

from ._base import manual_dir, processed_dir, stamp, write_parquet

COLUMNS = ["study", "year", "geography", "group_dim", "group_value", "d_share_2p", "r_share_2p",
           "turnout_rate", "n", "moe"]


def ingest_validated_voter() -> pd.DataFrame:
    """Load data/manual/validated_voter_priors.csv. Studies disagree by 3-5 pts; the spread is used downstream."""
    df = pd.read_csv(manual_dir() / "validated_voter_priors.csv")
    missing = [c for c in COLUMNS if c not in df]
    if missing:
        raise ValueError(f"validated_voter_priors.csv missing columns: {missing}")
    df = stamp(df[COLUMNS + [c for c in ("source_url", "note") if c in df]], "manual:validated_voter_priors.csv", "manual", "manual")
    write_parquet(df, processed_dir() / "validated_voter_priors.parquet")
    return df
