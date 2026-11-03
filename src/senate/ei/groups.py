"""EI groups, regions and per-county group voter counts n_ig (plan §6.6)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import structlog

log = structlog.get_logger()

GROUPS = ["wnh_college", "wnh_noncollege", "black", "hispanic", "asian", "other"]
DEFAULT_COLLEGE_SHARE_WNH = 0.38  # national share of white non-Hispanic adults with a bachelor's+ (used when edu_county is absent)

_STATE_REGION = {
    **dict.fromkeys("CT ME MA NH RI VT NJ NY PA".split(), "northeast"),
    **dict.fromkeys("IL IN IA KS MI MN MO NE ND OH SD WI".split(), "midwest"),
    **dict.fromkeys("AL AR DE FL GA KY LA MD MS NC OK SC TN TX VA WV".split(), "south"),
    **dict.fromkeys("AZ CO ID MT NV NM UT WY".split(), "mountain"),
    **dict.fromkeys("AK CA HI OR WA".split(), "pacific"),
}
BLACK_BELT_STATES = set("AL AR FL GA LA MS NC SC TN VA".split())
BLACK_BELT_MIN_BLACK = 0.35  # county black CVAP share
RIO_GRANDE_STATES = set("AZ NM TX".split())
RIO_GRANDE_MIN_HISP = 0.50  # county Hispanic CVAP share
REGIONS = ["northeast", "midwest", "south", "black_belt", "rio_grande", "mountain", "pacific"]

# Census divisions, used to pool states with fewer than ei.min_counties_for_state_run counties.
DIVISION = {
    **dict.fromkeys("CT ME MA NH RI VT".split(), "new_england"),
    **dict.fromkeys("NJ NY PA".split(), "mid_atlantic"),
    **dict.fromkeys("IL IN MI OH WI".split(), "east_north_central"),
    **dict.fromkeys("IA KS MN MO NE ND SD".split(), "west_north_central"),
    **dict.fromkeys("DE FL GA MD NC SC VA WV".split(), "south_atlantic"),
    **dict.fromkeys("AL KY MS TN".split(), "east_south_central"),
    **dict.fromkeys("AR LA OK TX".split(), "west_south_central"),
    **dict.fromkeys("AZ CO ID MT NV NM UT WY".split(), "mountain"),
    **dict.fromkeys("AK CA HI OR WA".split(), "pacific"),
}


def assign_regions(state_po: pd.Series, cvap_wide: pd.DataFrame | None = None) -> pd.Series:
    """Pooling region per county. Black Belt / Rio Grande are county-level carve-outs of the southern / southwestern
    states by CVAP share (documented rule; plan §6.7 lists the regions but not the county membership)."""
    reg = state_po.map(_STATE_REGION).fillna("midwest")
    if cvap_wide is not None:
        tot = cvap_wide[["wnh", "black", "hisp", "asian", "other"]].sum(axis=1).replace(0, np.nan)
        bb = (state_po.isin(BLACK_BELT_STATES)) & (cvap_wide["black"] / tot >= BLACK_BELT_MIN_BLACK)
        rg = (state_po.isin(RIO_GRANDE_STATES)) & (cvap_wide["hisp"] / tot >= RIO_GRANDE_MIN_HISP)
        reg = reg.mask(bb.fillna(False), "black_belt").mask(rg.fillna(False), "rio_grande")
    return reg


def cvap_wide(cvap: pd.DataFrame) -> pd.DataFrame:
    return cvap.pivot_table(index="geoid", columns="race5", values="cvap", aggfunc="sum", fill_value=0)


def build_county_groups(votes: pd.DataFrame, cvap: pd.DataFrame, edu: pd.DataFrame | None, kappa: dict[str, float],
                        groups: list[str] | None = None) -> pd.DataFrame:
    """One row per (geoid, group): CVAP, share of voters pi_ig and estimated voters n_ig = V_i * pi_ig.

    votes: geoid, state_po, votes_d, votes_r (a single year). V_i is the two-party vote so the EI model explains the
    two-party D share. pi_ig is proportional to CVAP_ig * kappa_g (relative turnout), normalised to sum to 1 so
    sum_g n_ig = V_i. College share of WNH CVAP comes from edu_county, else DEFAULT_COLLEGE_SHARE_WNH (flagged).
    """
    groups = groups or GROUPS
    w = cvap_wide(cvap)
    w = w.reindex(votes.geoid).fillna(0.0)
    if edu is not None and len(edu):
        cs = edu.drop_duplicates("geoid").set_index("geoid").college_share_wnh.reindex(votes.geoid)
        cs_src = np.where(cs.isna(), "default", "acs")
        cs = cs.fillna(DEFAULT_COLLEGE_SHARE_WNH).clip(0, 1)
    else:
        cs = pd.Series(DEFAULT_COLLEGE_SHARE_WNH, index=votes.geoid)
        cs_src = np.full(len(votes), "default")
    cv = pd.DataFrame({
        "wnh_college": w["wnh"].to_numpy() * cs.to_numpy(),
        "wnh_noncollege": w["wnh"].to_numpy() * (1 - cs.to_numpy()),
        "black": w["black"].to_numpy(), "hispanic": w["hisp"].to_numpy(),
        "asian": w["asian"].to_numpy(), "other": w["other"].to_numpy(),
    }, index=votes.geoid)[groups]
    k = np.array([kappa[g] for g in groups])
    eff = cv.to_numpy() * k
    tot = eff.sum(axis=1, keepdims=True)
    pi = np.divide(eff, tot, out=np.full_like(eff, 1.0 / len(groups)), where=tot > 0)
    v = (votes.votes_d + votes.votes_r).to_numpy(float)
    out = pd.DataFrame({
        "geoid": np.repeat(votes.geoid.to_numpy(), len(groups)),
        "group": np.tile(groups, len(votes)),
        "cvap_g": cv.to_numpy().ravel(),
        "pi": pi.ravel(),
        "n_group": (pi * v[:, None]).ravel(),
        "edu_source": np.repeat(cs_src, len(groups)),
    })
    return out


def wide(df: pd.DataFrame, col: str, groups: list[str] | None = None) -> pd.DataFrame:
    return df.pivot(index="geoid", columns="group", values=col)[groups or GROUPS]
