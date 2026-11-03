"""FIPS helpers: zero-padding, state lookup, exclusions."""
from __future__ import annotations

import pandas as pd

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10",
    "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19",
    "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35",
    "NY": "36", "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44",
    "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56",
}
FIPS_STATE = {v: k for k, v in STATE_FIPS.items()}
DC_COUNTY = "11001"
CT_PLANNING_REGIONS = {
    "09110": "Capitol", "09120": "Greater Bridgeport", "09130": "Lower Connecticut River Valley",
    "09140": "Naugatuck Valley", "09150": "Northeastern Connecticut", "09160": "Northwest Hills",
    "09170": "South Central Connecticut", "09180": "Southeastern Connecticut", "09190": "Western Connecticut",
}


def pad_county(s: pd.Series) -> pd.Series:
    """Zero-pad to 5 chars, stripping a trailing '.0' left by float parsing."""
    return s.astype(str).str.replace(r"\.0$", "", regex=True).str.strip().str.zfill(5)


def state_po_from_geoid(geoid: pd.Series) -> pd.Series:
    return geoid.str[:2].map(FIPS_STATE)
