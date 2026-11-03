"""Baseline two-party margins (plan §6.1)."""
from __future__ import annotations

import pandas as pd


def baseline_margin(votes_d: int, votes_r: int) -> float:
    if votes_d + votes_r == 0:
        raise ValueError("baseline_margin: zero two-party votes")
    return 100.0 * (votes_d - votes_r) / (votes_d + votes_r)


def state_baselines(votes: pd.DataFrame) -> pd.DataFrame:
    """votes: state_po, votes_d, votes_r (one row per county OR per state). State margins come from summed votes,
    never from averaging county margins. Returns state_po, votes_d, votes_r, m0."""
    s = votes.groupby("state_po", as_index=False)[["votes_d", "votes_r"]].sum()
    s["m0"] = [baseline_margin(d, r) for d, r in zip(s.votes_d, s.votes_r)]
    return s


def national_margin(votes: pd.DataFrame) -> float:
    """NPV margin (two-party, points) from summed votes."""
    return baseline_margin(votes.votes_d.sum(), votes.votes_r.sum())
