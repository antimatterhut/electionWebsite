"""Plan §11.3 data checks plus the ingest cleaning logic and the manual-fallback path (§11.2)."""
from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
import pytest

from senate import schemas
from senate.geo import crosswalks
from senate.ingest import acs_cvap, crosstabs, pres_results, senate_polls, validated_voter
from senate.ingest import generic_ballot
from senate.io import FetchError
from tests.conftest import FakeResponse


# ---------------------------------------------------------------- races_2026
def test_35_races(dirs):
    races = pd.read_csv(dirs["manual"] / "races_2026.csv", keep_default_na=False)
    races["special"] = races.special.astype(str).str.lower() == "true"
    races["rcv"] = races.rcv.astype(str).str.lower() == "true"
    schemas.races_2026.validate(races)
    assert len(races) == 35
    assert races["class"].value_counts().to_dict() == {2: 33, 3: 2}
    assert set(races[races.special].state_po) == {"OH", "FL"}
    assert set(races[races.rcv].state_po) == {"ME", "AK"}


# ---------------------------------------------------------------- pres results
def _medsl_rows():
    def row(year, fips, party, cand, votes, total, mode="TOTAL"):
        return dict(year=year, state="X", state_po="XX", county_name="c", county_fips=fips, office="US PRESIDENT",
                    candidate=cand, party=party, candidatevotes=float(votes), totalvotes=float(total), mode=mode)

    rows = []
    for year in (2020, 2024):
        rows += [row(year, "1001", "DEMOCRAT", "D", 380, 535), row(year, "1001", "REPUBLICAN", "R", 140, 535),
                 row(year, "1001", "LIBERTARIAN", "L", 5, 535)]
        # split modes must be summed; DC must be dropped
        rows += [row(year, "13121", "DEMOCRAT", "D", 60, 100, "EARLY"), row(year, "13121", "DEMOCRAT", "D", 40, 80, "MAIL"),
                 row(year, "13121", "REPUBLICAN", "R", 30, 100, "EARLY"), row(year, "13121", "REPUBLICAN", "R", 20, 80, "MAIL")]
        rows += [row(year, "11001", "DEMOCRAT", "D", 9, 10), row(year, "46113", "DEMOCRAT", "D", 5, 8),
                 row(year, "46113", "REPUBLICAN", "R", 3, 8)]
    rows.append(dict(rows[0], office="US SENATE"))
    return pd.DataFrame(rows)


def test_clean_medsl():
    out = pres_results.clean_medsl(_medsl_rows())
    schemas.pres_county.validate(out.assign(source="t", retrieved_at=pd.Timestamp.now(), data_quality_flag="ok"))
    a = out[(out.year == 2024) & (out.geoid == "01001")].iloc[0]
    assert (a.votes_d, a.votes_r, a.votes_other, a.votes_total) == (380, 140, 5, 535)
    assert a.margin_2p == pytest.approx(100 * 240 / 520, rel=1e-4)
    g = out[(out.year == 2024) & (out.geoid == "13121")].iloc[0]
    assert (g.votes_d, g.votes_r, g.votes_total) == (100, 50, 180)
    assert "11001" not in set(out.geoid)  # DC dropped
    assert "46113" not in set(out.geoid) and "46102" in set(out.geoid)  # Shannon -> Oglala Lakota
    assert a.state_po == "AL" and g.state_po == "GA"


def test_pres_results_manual_fallback_when_download_blocked(dirs, fake_fetcher):
    medsl = _medsl_rows().drop(columns=["state_po"])
    medsl.to_csv(dirs["manual"] / "countypres_2000-2024.csv", index=False)
    f = fake_fetcher({"robots.txt": FakeResponse(200, text=""), "dataverse": FakeResponse(400)})
    df = pres_results.ingest_pres_results(f, allow_fallback=True)
    assert set(df.data_quality_flag) == {"manual"}
    assert (dirs["processed"] / "pres_county.parquet").exists()
    with pytest.raises(FetchError):
        pres_results.ingest_pres_results(f, allow_fallback=False)


def test_pres_results_without_any_manual_data_fails_loudly(dirs, fake_fetcher):
    f = fake_fetcher({"robots.txt": FakeResponse(200, text=""), "dataverse": FakeResponse(400)})
    with pytest.raises(FileNotFoundError, match="no manual presidential results"):
        pres_results.ingest_pres_results(f)


# ---------------------------------------------------------------- CVAP
def _cvap_raw():
    rows = []
    for geoid, tot, parts in [("05000US01001", 1000, {"White Alone": 600, "Black or African American Alone": 250,
                                                       "Hispanic or Latino": 100, "Asian Alone": 20}),
                              ("05000US11001", 500, {"White Alone": 250})]:
        rows.append(dict(geoname="c", lntitle="Total", geoid=geoid, cvap_est=tot, cvap_moe=10))
        rows += [dict(geoname="c", lntitle=k, geoid=geoid, cvap_est=v, cvap_moe=5) for k, v in parts.items()]
    return pd.DataFrame(rows)


def test_parse_cvap_county_shares_and_moe():
    out = acs_cvap.parse_cvap_county(_cvap_raw())
    out = out.assign(source="t", retrieved_at=pd.Timestamp.now(), data_quality_flag="ok")
    schemas.cvap_county.validate(out)
    assert schemas.cvap_shares_sum_to_one(out)
    assert set(out.geoid) == {"01001"}  # DC dropped
    other = out[out.race5 == "other"].iloc[0]
    assert other.cvap == 30 and other.moe >= 10  # 1000 - (600+250+100+20), MOE sqrt-sum-squares
    assert (out.moe >= 0).all()


def test_age_shares_sum_to_one():
    cols = {v: [10.0] for vs in acs_cvap.AGE_VARS.values() for v in vs}
    sh = acs_cvap.age_shares(pd.DataFrame({**cols, "geoid": ["01001"]}))
    assert sh.cvap_share.sum() == pytest.approx(1.0)
    assert set(sh.age_bin) == set(acs_cvap.AGE_VARS)


def test_acs_requires_key(monkeypatch, fake_fetcher):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CENSUS_API_KEY"):
        acs_cvap._acs(fake_fetcher({}), 2023, ["B01001_001E"])


# ---------------------------------------------------------------- polls schemas + fallbacks
def _good_polls():
    return pd.DataFrame({
        "poll_id": ["a", "b"], "pollster": ["A", "B"], "field_start": ["2026-10-01", "2026-10-02"],
        "field_end": ["2026-10-03", "2026-10-02"], "pop": ["LV", "RV"], "d_pct": [50.0, 47.0], "r_pct": [42.0, 45.0],
        "source": "t", "retrieved_at": pd.Timestamp.now(), "data_quality_flag": "ok"})


def test_generic_poll_schema_rejects_bad_rows():
    schemas.generic_polls.validate(_good_polls())
    for mutate in (lambda d: d.__setitem__("field_end", ["2026-09-01", "2026-10-02"]),
                   lambda d: d.__setitem__("d_pct", [60.0, 47.0]),  # 60 + 42 > 100
                   lambda d: d.__setitem__("pop", ["LV", "XX"]),
                   lambda d: d.__setitem__("poll_id", ["a", "a"]) or d.__setitem__("pop", ["LV", "LV"])):
        bad = _good_polls()
        mutate(bad)
        with pytest.raises(pa.errors.SchemaError):
            schemas.generic_polls.validate(bad)


def test_senate_poll_schema():
    d = _good_polls().rename(columns={"d_pct": "dside_pct", "r_pct": "rside_pct"})
    d["state_po"], d["matchup_type"] = "GA", "two_way"
    schemas.senate_polls.validate(d)
    d["matchup_type"] = "weird"
    with pytest.raises(pa.errors.SchemaError):
        schemas.senate_polls.validate(d)


def test_pres_schema_rejects_votes_over_total():
    row = dict(year=2024, geoid="01001", state_po="AL", votes_d=6, votes_r=5, votes_other=0, votes_total=10,
               margin_2p=1.0, source="t", retrieved_at=pd.Timestamp.now(), data_quality_flag="ok")
    with pytest.raises(pa.errors.SchemaError):
        schemas.pres_county.validate(pd.DataFrame([row]))
    with pytest.raises(pa.errors.SchemaError):  # duplicate (year, geoid)
        schemas.pres_county.validate(pd.DataFrame([dict(row, votes_total=20)] * 2))


def test_polls_fall_back_to_manual_when_network_blocked(dirs, fake_fetcher):
    manual_generic = _good_polls().drop(columns=["source", "retrieved_at", "data_quality_flag"])
    manual_generic["n"], manual_generic["sponsor"], manual_generic["mode"] = 800, "", ""
    manual_generic["und_pct"], manual_generic["partisan"], manual_generic["source_url"] = 5.0, False, "m"
    manual_generic.to_csv(dirs["manual"] / "generic_polls.csv", index=False)
    f = fake_fetcher({"robots.txt": FakeResponse(200, text="")})  # everything else 404s
    g = generic_ballot.ingest_generic_polls(f)
    assert set(g.data_quality_flag) == {"manual"} and len(g) == 2
    schemas.generic_polls.validate(g)

    s = senate_polls.ingest_senate_polls(["GA"], f)  # header-only manual file => empty but flagged path taken
    assert s.empty
    with pytest.raises(FetchError):
        generic_ballot.ingest_generic_polls(f, allow_fallback=False)


def test_manual_tables_load(dirs):
    pd.DataFrame([dict(study="pew", year=2024, geography="national", group_dim="race", group_value="black",
                       d_share_2p=0.86, r_share_2p=0.14, turnout_rate=0.6, n=1000, moe=3.0)]
                 ).to_csv(dirs["manual"] / "validated_voter_priors.csv", index=False)
    assert len(validated_voter.ingest_validated_voter()) == 1
    pd.DataFrame([dict(poll_id="p", geography="national", group_dim="edu_race", group_value="White, no college",
                       n_group=500, dside_pct=35, rside_pct=62),
                  dict(poll_id="p", geography="national", group_dim="race", group_value="Asian",
                       n_group=40, dside_pct=60, rside_pct=36)]
                 ).to_csv(dirs["manual"] / "crosstabs.csv", index=False)
    pd.DataFrame({"poll_label": ["White, no college"], "canonical": ["wnh_noncollege"]}
                 ).to_csv(dirs["manual"] / "group_map.csv", index=False)
    ct = crosstabs.ingest_crosstabs()
    assert ct.group_value.tolist() == ["wnh_noncollege"]  # n_group 40 < min_n 75 dropped
    assert ct.margin_2p.iloc[0] == pytest.approx(100 * (35 - 62) / 97)


# ---------------------------------------------------------------- crosswalks
def test_fips_aliases_map_retired_codes():
    s = pd.Series(["46113", "46102", "02270", "51515"])
    assert crosswalks.apply_fips_aliases(s, 2024).tolist() == ["46102", "46102", "02158", "51019"]


def test_fips_aliases_respect_validity_window(tmp_path):
    pd.DataFrame({"old_geoid": ["99001"], "new_geoid": ["99002"], "valid_from": [2000], "valid_to": [2010]}
                 ).to_csv(tmp_path / "fips_aliases.csv", index=False)
    s = pd.Series(["99001"])
    assert crosswalks.apply_fips_aliases(s, 2005, tmp_path).tolist() == ["99002"]
    assert crosswalks.apply_fips_aliases(s, 2020, tmp_path).tolist() == ["99001"]


def test_town_aggregation(tmp_path):
    pd.DataFrame({"town_geoid": ["t1", "t2", "t3"], "county_geoid": ["23001", "23001", "23003"]}
                 ).to_csv(tmp_path / "town_to_county.csv", index=False)
    df = pd.DataFrame({"town_geoid": ["t1", "t2", "t3"], "year": [2024] * 3, "votes_d": [1, 2, 4]})
    out = crosswalks.towns_to_counties(df, ["votes_d"], tmp_path).sort_values("geoid")
    assert out.votes_d.tolist() == [3, 4] and out.geoid.tolist() == ["23001", "23003"]
    with pytest.raises(ValueError, match="missing"):
        crosswalks.towns_to_counties(df.assign(town_geoid=["t1", "t2", "zz"]), ["votes_d"], tmp_path)


def test_ak_pop_weighted_split(tmp_path):
    pd.DataFrame({"house_district": ["1", "1"], "borough_geoid": ["02020", "02170"], "weight_pop": [0.75, 0.25]}
                 ).to_csv(tmp_path / "ak_district_to_borough.csv", index=False)
    out = crosswalks.ak_districts_to_boroughs(pd.DataFrame({"house_district": ["1"], "votes_d": [100]}),
                                              ["votes_d"], tmp_path).sort_values("geoid")
    assert out.votes_d.tolist() == [75, 25]


def test_senate_polls_deduped_across_tables_prefers_two_way():
    base = dict(poll_id="x", pop="LV", state_po="GA")
    df = pd.DataFrame([dict(base, matchup_type="multi", dside_pct=50.0), dict(base, matchup_type="two_way", dside_pct=52.0),
                       dict(base, poll_id="y", matchup_type="multi", dside_pct=40.0)])
    out = senate_polls.dedupe_across_tables(df)
    assert out.set_index("poll_id").dside_pct.to_dict() == {"x": 52.0, "y": 40.0}


def test_acs_fallback_error_names_both_failures(dirs, fake_fetcher, monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    f = fake_fetcher({"robots.txt": FakeResponse(200, text="")})
    with pytest.raises(RuntimeError, match="no manual fallback"):
        acs_cvap.ingest_acs_cvap(f)
