"""Task 0 (MODEL_FIXES): county vote sums must reconcile to the state totals (no per-mode double counting)."""
from __future__ import annotations

import pandas as pd
import pytest

from senate.config import ROOT
from senate.ingest.pres_results import clean_medsl

FULL = ROOT / "data" / "manual" / "countypres_2000-2024.csv"
# Known MEDSL-vs-state-file source differences (MEDSL matches certified totals; the backtest state file is older).
LOOSE = {(2020, "KS"), (2024, "ME"), (2024, "OR")}


@pytest.fixture(scope="module")
def cleaned():
    if not FULL.exists():
        pytest.skip("MEDSL file not present")
    raw = pd.read_csv(FULL, dtype=str).astype({"year": int, "candidatevotes": float, "totalvotes": float})
    return clean_medsl(raw)


def _margin(d, r):
    return 100.0 * (d - r) / (d + r)


@pytest.mark.parametrize("year", [2020, 2024])
def test_state_sums_match_state_file(cleaned, year):
    st = pd.read_csv(ROOT / "data" / "manual" / "backtest" / f"pres_state_{year}.csv").set_index("state_po")
    g = cleaned[cleaned.year == year].groupby("state_po")[["votes_d", "votes_r"]].sum()
    assert set(g.index) == set(st.index)
    for s in g.index:
        tol = 0.025 if (year, s) in LOOSE else 0.005
        assert abs(g.loc[s, "votes_d"] / st.loc[s, "votes_d"] - 1) < tol, (year, s, "D")
        assert abs(g.loc[s, "votes_r"] / st.loc[s, "votes_r"] - 1) < tol, (year, s, "R")
        assert abs(_margin(*g.loc[s, ["votes_d", "votes_r"]]) - _margin(*st.loc[s, ["votes_d", "votes_r"]])) < 0.6, (year, s)
    t, ts = g.sum(), st.sum()
    assert abs(_margin(t.votes_d, t.votes_r) - _margin(ts.votes_d, ts.votes_r)) < 0.1


def test_2024_npv_margin(cleaned):
    t = cleaned[cleaned.year == 2024][["votes_d", "votes_r"]].sum()
    assert _margin(t.votes_d, t.votes_r) == pytest.approx(-1.69, abs=0.05)


def test_total_rows_not_added_to_modes():
    rows = []
    for mode, d, r in (("TOTAL", 60, 40), ("EARLY VOTING", 30, 20), ("ELECTION DAY", 30, 20)):
        for cand, party, v in (("D", "DEMOCRAT", d), ("R", "REPUBLICAN", r)):
            rows.append(dict(year=2024, office="US PRESIDENT", county_fips="01001", candidate=cand, party=party,
                             candidatevotes=float(v), totalvotes=100.0, mode=mode))
    out = clean_medsl(pd.DataFrame(rows))
    assert out.votes_d.iloc[0] == 60 and out.votes_r.iloc[0] == 40
