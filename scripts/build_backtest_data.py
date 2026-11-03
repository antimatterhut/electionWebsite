"""Build the Phase 2 backtest / baseline inputs under data/manual/backtest/ (plan §7.1-7.2, §4.9).

Sources (all public, fetched through senate.io.Fetcher: UA, robots, rate limit, cache):
  * 538 historical poll archives (Wayback Machine copies; fivethirtyeight.com now redirects away)
  * tonmcg/US_County_Level_Election_Results_08-{20,24} county presidential returns -> state two-party sums
  * Wikipedia "<year> United States Senate election in <State>" results tables -> Senate truth

Outputs (committed, hand-reviewable CSVs):
  pres_state_{2016,2020,2024}.csv     state_po, votes_d, votes_r
  {2018,2022}/senate_polls.csv        senate_polls schema + tracking; `race` = 'regular' | 'special'
  {2018,2022}/generic_polls.csv       generic_polls schema + tracking
  {2018,2022}/senate_truth.csv        year, state_po, race, votes_d, votes_r, dside_name, rside_name
  data/manual/pollster_ratings.csv    seeded from the 538 numeric_grade (0-3) when empty
Run: python scripts/build_backtest_data.py [--skip-truth]
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from senate.geo.fips import STATE_FIPS  # noqa: E402
from senate.ingest import _polls as P  # noqa: E402
from senate.io import FetchError, Fetcher  # noqa: E402

OUT = ROOT / "data" / "manual" / "backtest"
WAYBACK = "https://web.archive.org/web/2024id_/https://projects.fivethirtyeight.com/polls-page/data/{}.csv"
TONMCG = "https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-{yy}/master/{y}_US_County_Level_Presidential_Results.csv"

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}
NAME_TO_PO = {v: k for k, v in STATE_NAMES.items()}

# (state, race) for every Senate contest on the November ballot.
RACES = {
    2018: [(s, "regular") for s in "AZ CA CT DE FL HI IN ME MD MA MI MN MS MO MT NE NV NJ NM NY ND OH PA RI TN TX UT VT VA WA WV WI WY".split()]
          + [("MN", "special"), ("MS", "special")],
    2022: [(s, "regular") for s in "AL AK AZ AR CA CO CT FL GA HI ID IL IN IA KS KY LA MD MO NV NH NY NC ND OH OK OR PA SC SD UT VT WA WI".split()]
          + [("OK", "special")],
}
# independents who caucus with / were endorsed by Democrats and stand in for the D-side (plan §2.2)
DSIDE_INDEPENDENT = {(2018, "VT"): "Sanders", (2018, "ME"): "King", (2022, "UT"): "McMullin"}
# No usable two-party contest: CA 2018 (two Democrats), AK 2022 (ranked-choice, two Republicans lead; no
# final-round D-vs-R), and the 2018 MS special (four-candidate jungle, no party column in the results table).
# 538 labels special-election seats only by Senate class: (cycle, state, seat_name)
SPECIAL_SEATS = {(2018, "MN", "Class II"), (2022, "OK", "Class II")}
NO_TWO_PARTY = {(2018, "CA", "regular"), (2022, "AK", "regular"), (2018, "MS", "special")}


# ---------------------------------------------------------------- presidential baselines
def _state_from_label(label: str) -> str | None:
    """'Maine �' / 'Nebraska [a]' -> 'ME' / 'NE'; district rows ('ME-1Tooltip ...') and totals -> None."""
    t = re.sub(r"[^A-Za-z .]", "", str(label)).strip()
    return NAME_TO_PO.get(t)


def _pres_2016_from_wikipedia(f: Fetcher) -> pd.DataFrame:
    """The tonmcg 2016 county file is incomplete (e.g. CA 7.4M Clinton votes), so 2016 comes from the Wikipedia
    state-results table."""
    html = f.get("https://en.wikipedia.org/wiki/2016_United_States_presidential_election", "wikipedia_pres2016")
    for t in pd.read_html(io.StringIO(html.decode("utf-8", "replace")), match="Alabama"):
        if t.shape[1] >= 8 and isinstance(t.columns[1], tuple) and "Clinton" in t.columns[1][0]:
            name = t.iloc[:, 0].astype(str).str.replace(r"\[.*?\]|\(.*?\)", "", regex=True).str.strip()
            out = pd.DataFrame({"state_po": name.map(_state_from_label), "votes_d": t.iloc[:, 1].map(P.parse_votes),
                                "votes_r": t.iloc[:, 4].map(P.parse_votes)})
            return out.dropna().astype({"votes_d": int, "votes_r": int})
    raise ValueError("2016 state results table not found")


def build_pres_state(f: Fetcher) -> None:
    for year in (2016, 2020, 2024):
        if year == 2016:
            s = _pres_2016_from_wikipedia(f).groupby("state_po", as_index=False).first()
        else:
            raw = f.get(TONMCG.format(yy=20 if year == 2020 else 24, y=year), f"tonmcg_{year}")
            df = pd.read_csv(io.BytesIO(raw), low_memory=False)
            df["votes_d"], df["votes_r"] = df["votes_dem"], df["votes_gop"]
            df["state_po"] = df["state_name"].map(NAME_TO_PO)
            df = df[df.state_po.isin(STATE_NAMES)]
            s = df.groupby("state_po")[["votes_d", "votes_r"]].sum().round().astype(int).reset_index()
        assert len(s) == 50, (year, len(s))
        s.to_csv(OUT / f"pres_state_{year}.csv", index=False)
        print(f"pres_state_{year}: D {s.votes_d.sum():,} R {s.votes_r.sum():,}")


# ---------------------------------------------------------------- 538 archive polls
def _pop(x: str) -> str:
    x = str(x).lower()
    return {"lv": "LV", "rv": "RV", "v": "RV", "a": "A"}.get(x, "A")


def _norm_name(x: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(x).lower())


def _poll_rows(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    """One output row per (poll_id, population): the question with the fewest candidates that has a D and an R."""
    df = df.copy()
    df["start_date"] = pd.to_datetime(df.start_date, format="%m/%d/%y", errors="coerce")
    df["end_date"] = pd.to_datetime(df.end_date, format="%m/%d/%y", errors="coerce")
    df = df[df.end_date.notna() & (df.hypothetical.astype(str).str.lower() != "true")]
    df["party"] = df.party.astype(str)
    rows = []
    for qid, q in df.groupby("question_id", sort=False):
        d_over = q.attrs.get("d_over")
        first = q.iloc[0]
        if kind == "senate":
            ind = DSIDE_INDEPENDENT.get((int(first.cycle), STATE_ABBR.get(first.state)))
            if ind and q.candidate_name.str.contains(ind, case=False).any():
                dside = q[q.candidate_name.str.contains(ind, case=False)].pct.max()
                dmask = q.candidate_name.str.contains(ind, case=False)
            else:
                dmask = q.party == "DEM"
                dside = q[dmask].pct.max() if dmask.any() else np.nan
        else:
            dmask = q.party == "DEM"
            dside = q[dmask].pct.max() if dmask.any() else np.nan
        rmask = q.party == "REP"
        if not dmask.any() or not rmask.any():
            continue
        other = q[~dmask & ~rmask].pct.sum()
        rows.append({
            "qid": qid, "poll_id_538": first.poll_id, "state": first.state if kind == "senate" else "",
            "pollster": first.pollster, "sponsor": str(first.sponsors) if pd.notna(first.sponsors) else "",
            "field_start": first.start_date.date() if pd.notna(first.start_date) else first.end_date.date(),
            "field_end": first.end_date.date(), "n": first.sample_size, "pop": _pop(first.population),
            "mode": str(first.methodology) if pd.notna(first.methodology) else "",
            "dside_pct": dside, "rside_pct": q[rmask].pct.max(), "other_pct": other if other else np.nan,
            "n_cand": len(q), "partisan": bool(pd.notna(first.partisan) or str(first.internal).lower() == "true"),
            "tracking": str(first.tracking).lower() == "true", "rating_name": first.pollster_rating_name,
            "grade": first.numeric_grade, "seat_name": str(first.get("seat_name", "")), "stage": first.stage,
            "race_id": first.race_id, "source_url": first.url if pd.notna(first.url) else "",
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.sort_values(["poll_id_538", "pop", "n_cand"]).drop_duplicates(["poll_id_538", "pop"])
    out["matchup_type"] = np.where(out.n_cand > 2, "multi", "two_way")
    return out


STATE_ABBR = {v: k for k, v in STATE_NAMES.items()}


def _generic_rows(df: pd.DataFrame) -> pd.DataFrame:
    """538 generic-ballot archive is wide (dem/rep/ind columns): one row per question and population."""
    df = df.copy()
    df["end_date"] = pd.to_datetime(df.end_date, format="%m/%d/%y", errors="coerce")
    df["start_date"] = pd.to_datetime(df.start_date, format="%m/%d/%y", errors="coerce")
    df = df[df.end_date.notna() & df.dem.notna() & df.rep.notna()]
    out = pd.DataFrame({
        "poll_id_538": df.poll_id, "pollster": df.pollster,
        "sponsor": df.sponsors.fillna("").astype(str), "field_start": df.start_date.fillna(df.end_date).dt.date,
        "field_end": df.end_date.dt.date, "n": df.sample_size, "pop": df.population.map(_pop),
        "mode": df.methodology.fillna("").astype(str), "dside_pct": df.dem, "rside_pct": df.rep,
        "other_pct": df.ind, "partisan": df.partisan.notna() | (df.internal.astype(str).str.lower() == "true"),
        "tracking": df.tracking.astype(str).str.lower() == "true", "rating_name": df.pollster_rating_name,
        "grade": df.numeric_grade, "source_url": df.url.fillna("")})
    return out.drop_duplicates(["poll_id_538", "pop"])


def build_polls(f: Fetcher) -> pd.DataFrame:
    """Writes {cycle}/{senate,generic}_polls.csv and returns the pollster-rating table (all cycles)."""
    ratings = []
    for kind, fname in (("senate", "senate_polls_historical"), ("generic", "generic_ballot_polls_historical")):
        raw = f.get(WAYBACK.format(fname), f"538_{fname}")
        src = pd.read_csv(io.BytesIO(raw), low_memory=False)
        for cycle in (2018, 2022):
            d = src[src.cycle == cycle]
            if kind == "senate":
                d = d[(d.stage == "general")]
                d = d[d.state.isin(STATE_ABBR)]
                rows = _poll_rows(d, kind)
            else:
                rows = _generic_rows(d)
            ratings.append(rows[["rating_name", "grade"]].dropna())
            if kind == "senate":
                rows["state_po"] = rows.state.map(STATE_ABBR)
                rows["race"] = np.where(rows.apply(lambda r: (cycle, r.state_po, r.seat_name) in SPECIAL_SEATS, axis=1),
                                        "special", "regular")
                keep = ["poll_id_538", "state_po", "race", "pollster", "sponsor", "field_start", "field_end", "n", "pop",
                        "mode", "dside_pct", "rside_pct", "other_pct", "matchup_type", "partisan", "tracking",
                        "source_url"]
            else:
                rows = rows.rename(columns={"dside_pct": "d_pct", "rside_pct": "r_pct"})
                keep = ["poll_id_538", "pollster", "sponsor", "field_start", "field_end", "n", "pop", "mode",
                        "d_pct", "r_pct", "other_pct", "partisan", "tracking", "source_url"]
            rows = rows[keep].rename(columns={"poll_id_538": "poll_id"})
            rows["poll_id"] = [P.make_poll_id(f"{a}|{b}", c, d_, e) for a, b, c, d_, e in
                               zip(rows.pollster, rows["state_po"] if "state_po" in rows else [""] * len(rows), rows.field_end, rows.n, rows["pop"])]
            rows = rows.drop_duplicates(["poll_id", "pop"])
            (OUT / str(cycle)).mkdir(parents=True, exist_ok=True)
            rows.to_csv(OUT / str(cycle) / f"{kind}_polls.csv", index=False)
            print(f"{cycle} {kind}_polls: {len(rows)} rows")
    r = pd.concat(ratings)
    r["pollster"] = r.rating_name
    return r.groupby("pollster", as_index=False).grade.mean()


def seed_pollster_ratings(ratings: pd.DataFrame) -> None:
    p = ROOT / "data" / "manual" / "pollster_ratings.csv"
    if len(pd.read_csv(p)) > 0:
        return
    out = pd.DataFrame({"pollster": ratings.pollster, "rating": ratings.grade.clip(0, 3).round(2),
                        "source": "538 numeric_grade (2018/2022 archive)", "partisan_flag": False,
                        "last_reviewed": "2026-11-02"})
    out.to_csv(p, index=False)
    print(f"pollster_ratings: seeded {len(out)} rows")


# ---------------------------------------------------------------- Senate truth from Wikipedia
def _wiki_url(year: int, state: str, race: str) -> str:
    kind = "special_election" if race == "special" else "election"
    return f"https://en.wikipedia.org/wiki/{year}_United_States_Senate_{kind}_in_{STATE_NAMES[state].replace(' ', '_')}"


def _num(x) -> float:
    s = re.sub(r"\[.*?\]|[^\d.]", "", str(x))
    return float(s) if s else np.nan


def parse_truth(html: str, year: int, state: str) -> dict | None:
    """Pick the results table (D and R present, largest total votes) and sum votes by party."""
    best = None
    for t in P.read_html_tables(html):
        t = t.copy()
        t.columns = [" ".join(dict.fromkeys(map(str, c))) if isinstance(c, tuple) else str(c) for c in t.columns]
        cols = {c.lower(): c for c in t.columns}
        c_votes = next((c for k, c in cols.items() if k.startswith("votes")), None)
        c_cand = next((c for k, c in cols.items() if k.startswith("candidate")), None)
        pcols = [c for k, c in cols.items() if k.startswith("party")]
        if not c_votes or not c_cand or not pcols:
            continue
        c_party = pcols[-1]
        body = t[~t[c_cand].astype(str).str.contains("total|turnout|majority|swing|registered", case=False, na=True)]
        body = body[body[c_party].astype(str).str.contains("[A-Za-z]", na=False)].copy()
        body["v"] = body[c_votes].map(_num)
        body = body[body.v.notna() & (body.v > 0)]
        party = body[c_party].astype(str)
        isd = party.str.contains("democratic|dfl|democrat", case=False)
        isr = party.str.contains("republican", case=False)
        if not isd.any() and (year, state) not in DSIDE_INDEPENDENT:
            continue
        if not isr.any():
            continue
        total = body.v.sum()
        if best is None or total > best["total"]:
            best = {"total": total, "body": body.assign(c=body[c_cand].astype(str), p=party), "isd": isd, "isr": isr}
    if best is None:
        return None
    b, isd, isr = best["body"], best["isd"], best["isr"]
    ind = DSIDE_INDEPENDENT.get((year, state))
    if ind:
        dm = b.c.str.contains(ind, case=False)
        dv, dn = b[dm].v.sum(), ind
    else:
        dv, dn = b[isd].v.sum(), "; ".join(b[isd].c.str.replace(r"\[.*?\]", "", regex=True).head(2))
    rn = "; ".join(b[isr].c.str.replace(r"\[.*?\]", "", regex=True).head(2))
    return {"votes_d": int(dv), "votes_r": int(b[isr].v.sum()), "dside_name": dn, "rside_name": rn,
            "total_votes": int(best["total"])}


def build_truth(f: Fetcher) -> None:
    for year, races in RACES.items():
        rows = []
        for state, race in races:
            if (year, state, race) in NO_TWO_PARTY:
                continue
            try:
                html = f.get(_wiki_url(year, state, race), "wikipedia_truth").decode("utf-8", "replace")
                r = parse_truth(html, year, state)
            except FetchError as e:
                print("FETCH FAIL", year, state, race, str(e)[:80])
                continue
            if r is None:
                print("NO TABLE", year, state, race)
                continue
            rows.append({"year": year, "state_po": state, "race": race, **r})
        df = pd.DataFrame(rows)
        (OUT / str(year)).mkdir(parents=True, exist_ok=True)
        df.to_csv(OUT / str(year) / "senate_truth.csv", index=False)
        print(f"{year} senate_truth: {len(df)} races")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-truth", action="store_true")
    ap.add_argument("--skip-polls", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    f = Fetcher()
    try:
        build_pres_state(f)
        if not args.skip_polls:
            seed_pollster_ratings(build_polls(f))
        if not args.skip_truth:
            build_truth(f)
    finally:
        f.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
