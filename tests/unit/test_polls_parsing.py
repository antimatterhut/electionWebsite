from datetime import date

import pandas as pd

from senate.ingest import _polls as P
from senate.ingest.generic_ballot import normalize_generic_table
from senate.ingest.senate_polls import normalize_senate_table


def test_parse_date_range_variants():
    assert P.parse_date_range("Oct 20–23, 2026", 2026) == (date(2026, 10, 20), date(2026, 10, 23))
    assert P.parse_date_range("Oct 28 – Nov 2, 2026", 2026) == (date(2026, 10, 28), date(2026, 11, 2))
    assert P.parse_date_range("Oct 25, 2026", 2026) == (date(2026, 10, 25), date(2026, 10, 25))
    assert P.parse_date_range("garbage", 2026) == (None, None)


def test_parse_sample_and_pct():
    assert P.parse_sample("1,200 (LV)") == (1200, "LV")
    assert P.parse_sample("800 RV") == (800, "RV")
    assert P.parse_sample("1000 adults") == (1000, "A")
    assert P.parse_pct("51%[3]") == 51.0
    assert P.parse_pct("n/a") is None


def test_clean_pollster_strips_footnotes_and_flags_party():
    assert P.clean_pollster("InsiderAdvantage (R)[124]") == ("InsiderAdvantage", True)
    assert P.clean_pollster("Research Co.[123]") == ("Research Co.", False)


def test_read_html_tables_repairs_bad_rowspan():
    html = "<table><tr><th>a</th><th>b</th></tr><tr><td rowspan='2\"'>1</td><td>2</td></tr></table>"
    assert len(P.read_html_tables(html)) == 1


def test_dedupe_prefers_lv_over_rv():
    df = pd.DataFrame({"poll_id": ["a", "a", "b"], "pop": ["RV", "LV", "RV"]})
    out = P.dedupe_polls(df)
    assert len(out) == 3  # same id with different pop is kept; exact duplicates are dropped
    assert P.dedupe_polls(pd.concat([df, df])).shape[0] == 3


def test_tracker_overlap_keeps_one_per_gap():
    df = pd.DataFrame({"pollster": ["T"] * 3, "state_po": ["GA"] * 3,
                       "field_end": pd.to_datetime(["2026-10-01", "2026-10-03", "2026-10-09"])})
    out = P.drop_overlapping_trackers(df, 7, ["state_po"])
    assert list(out.field_end.dt.day) == [1, 9]


def _generic_table():
    return pd.DataFrame({
        "Poll source": ["Pollster A[1]", "Pollster B (R)"],
        "Date(s) administered": ["Oct 20–23, 2026", "Oct 24, 2026"],
        "Sample size": ["1,200 (LV)", "800 (RV)"],
        "Democratic": ["50%", "47%"], "Republican": ["42%", "45%"], "Undecided": ["8%", "8%"],
    })


def test_normalize_generic_table():
    out = normalize_generic_table(_generic_table(), 2026)
    assert list(out.pollster) == ["Pollster A", "Pollster B"]
    assert out.partisan.tolist() == [False, True]
    assert out.d_pct.tolist() == [50.0, 47.0]
    assert out.field_end.iloc[0] == date(2026, 10, 23)
    assert out.poll_id.is_unique


def test_normalize_generic_table_ignores_unrelated_tables():
    assert normalize_generic_table(pd.DataFrame({"State": ["AL"], "Seats": [7]}), 2026).empty


def test_normalize_senate_table_maps_nominees_by_surname():
    race = pd.Series({"state_po": "GA", "dside_name": "Jon Ossoff", "rside_name": "Mike Collins"})
    tbl = pd.DataFrame({
        "Poll source": ["X Poll"], "Date(s) administered": ["Oct 20–23, 2026"], "Sample size": ["600 (LV)"],
        "Jon Ossoff Democratic": ["52%"], "Mike Collins Republican": ["44%"], "Other": ["2%"], "Undecided": ["2%"],
    })
    out = normalize_senate_table(tbl, race, 2026, "http://u")
    assert out.dside_pct.iloc[0] == 52.0 and out.rside_pct.iloc[0] == 44.0
    assert out.matchup_type.iloc[0] == "multi"


def test_nominee_change_drops_polls_against_old_nominee():
    race = pd.Series({"state_po": "ME", "dside_name": "Troy Jackson", "rside_name": "Susan Collins"})
    tbl = pd.DataFrame({
        "Poll source": ["Old", "New"], "Date(s) administered": ["Aug 1–3, 2026", "Oct 1–3, 2026"],
        "Sample size": ["600 (LV)"] * 2,
        "Troy Jackson Democratic": ["45%"] * 2, "Susan Collins Republican": ["47%"] * 2,
    })
    changes = pd.DataFrame({"state_po": ["ME"], "old_name": ["Troy Jackson"], "new_name": ["X Y"],
                            "effective_date": ["2026-09-01"]})
    out = normalize_senate_table(tbl, race, 2026, "u", changes=changes)
    assert out.pollster.tolist() == ["New"]
