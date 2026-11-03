"""pandera schemas for processed tables (plan §11.3)."""
from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera import Check, Column, DataFrameSchema

PROVENANCE = {
    "source": Column(str),
    "retrieved_at": Column(nullable=False),
    "data_quality_flag": Column(str, Check.isin(["ok", "manual"])),
}

MIN_US_COUNTIES = 3100  # 3,143 counties + equivalents; CT regions replace 8 counties with 9


def _votes_ok(df: pd.DataFrame) -> bool:
    return bool(((df.votes_d + df.votes_r) <= df.votes_total).all())


pres_county = DataFrameSchema(
    {
        "year": Column(int, Check.isin([2020, 2024])),
        "geoid": Column(str, Check.str_matches(r"^\d{5}$")),
        "state_po": Column(str, nullable=False),
        "votes_d": Column(int, Check.ge(0)),
        "votes_r": Column(int, Check.ge(0)),
        "votes_other": Column(int, Check.ge(0)),
        "votes_total": Column(int, Check.ge(0)),
        "margin_2p": Column(float, Check.in_range(-100, 100)),
        **PROVENANCE,
    },
    checks=[Check(_votes_ok, error="votes_d + votes_r > votes_total")],
    unique=["year", "geoid"],
    coerce=True,
)

cvap_county = DataFrameSchema(
    {
        "geoid": Column(str, Check.str_matches(r"^\d{5}$")),
        "race5": Column(str, Check.isin(["wnh", "black", "hisp", "asian", "other"])),
        "cvap": Column(int, Check.ge(0)),
        "moe": Column(float, Check.ge(0)),
        **PROVENANCE,
    },
    unique=["geoid", "race5"],
    coerce=True,
)


def cvap_shares_sum_to_one(df: pd.DataFrame, tol: float = 0.01) -> bool:
    """Race shares within each county sum to 1 +/- tol (plan §11.3)."""
    tot = df.groupby("geoid").cvap.transform("sum")
    s = (df.cvap / tot.where(tot > 0)).groupby(df.geoid).sum().dropna()
    return bool(((s - 1).abs() <= tol).all())


def _poll_checks(d_col: str, r_col: str) -> list[Check]:
    return [
        Check(lambda df: (df.field_end >= df.field_start).all(), error="field_end < field_start"),
        Check(lambda df: ((df[d_col] + df[r_col]) <= 100).all(), error="d_pct + r_pct > 100"),
    ]


_poll_common = {
    "poll_id": Column(str),
    "pollster": Column(str),
    "field_start": Column("datetime64[ns]", coerce=True),
    "field_end": Column("datetime64[ns]", coerce=True),
    "pop": Column(str, Check.isin(["LV", "RV", "A"])),
}

generic_polls = DataFrameSchema(
    {**_poll_common, "d_pct": Column(float, Check.in_range(0, 100)), "r_pct": Column(float, Check.in_range(0, 100)),
     **PROVENANCE},
    checks=_poll_checks("d_pct", "r_pct"),
    unique=["poll_id", "pop"],
    coerce=True,
)

senate_polls = DataFrameSchema(
    {**_poll_common, "state_po": Column(str),
     "dside_pct": Column(float, Check.in_range(0, 100)), "rside_pct": Column(float, Check.in_range(0, 100)),
     "matchup_type": Column(str, Check.isin(["two_way", "multi", "rcv_final"])), **PROVENANCE},
    checks=_poll_checks("dside_pct", "rside_pct"),
    unique=["poll_id", "pop"],
    coerce=True,
)

races_2026 = DataFrameSchema(
    {
        "state_po": Column(str, Check.str_matches(r"^[A-Z]{2}$")),
        "class": Column(int, Check.isin([2, 3])),
        "special": Column(bool),
        "dside_party": Column(str, Check.isin(["D", "I"])),
        "rcv": Column(bool),
    },
    checks=[
        Check(lambda df: len(df) == 35, error="expected 35 races"),
        Check(lambda df: (df["class"] == 2).sum() == 33 and (df["class"] == 3).sum() == 2,
              error="expected 33 class-2 and 2 class-3 races"),
        Check(lambda df: df.special.sum() == 2, error="expected 2 specials"),
    ],
    unique=["state_po"],
    coerce=True,
)

SCHEMAS = {
    "pres_county": pres_county,
    "cvap_county": cvap_county,
    "generic_polls": generic_polls,
    "senate_polls": senate_polls,
}
validate = pa.check_types  # re-export convenience
