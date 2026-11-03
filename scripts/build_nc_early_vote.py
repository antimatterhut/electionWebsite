"""Build data/manual/early_vote_NC.csv, ev_final.csv (NC rows) and ev_party_group.csv (NC rows) from official NCSBE files.

Inputs (download first; they hold voter-level public records, so keep them OUT of the repo):
  https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/{yyyy_mm_dd}/absentee_{yyyymmdd}.zip   for 2022-11-08, 2024-11-05, 2026-11-03
Final ballots by party (NCSBE turnout tables, Table 2 'Voters Who Voted'):
  https://www.ncsbe.gov/results-data/voter-turnout/2022-general-election-turnout
  https://www.ncsbe.gov/results-data/voter-turnout/2024-general-election-turnout
Usage: python scripts/build_nc_early_vote.py <dir containing x_abs_YYYYMMDD/absentee_YYYYMMDD.csv>
Only ACCEPTED ballots count; rows are cumulative to days_out >= 1 (the final pre-election-day totals)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from senate.config import ROOT
from senate.ingest.early_vote import ELECTION_DAY, EV_COLUMNS, _age_bin, _party, cumulate

CYCLES = {2022: "20221108", 2024: "20241105", 2026: "20261103"}
FINAL = {  # NCSBE Table 2 'Voters Who Voted' (O = Libertarian + Green + other minor parties)
    2022: {"D": 1283988, "R": 1303696, "U": 1183891, "O": 15329},
    2024: {"D": 1797064, "R": 1876744, "U": 1983669, "O": 48384},
}
SRC = "https://www.ncsbe.gov/results-data/voter-turnout/{y}-general-election-turnout"


def load(d: Path, ymd: str) -> pd.DataFrame:
    df = pd.read_csv(d / f"x_abs_{ymd}" / f"absentee_{ymd}.csv", dtype=str, encoding="latin-1",
                     usecols=["voter_party_code", "ballot_rtn_dt", "ballot_rtn_status", "age", "race", "ethnicity", "ballot_req_type"])
    df = df[df.ballot_rtn_status.str.upper().str.startswith("ACCEPT", na=False)].copy()
    df["date"] = pd.to_datetime(df.ballot_rtn_dt, errors="coerce")
    return df


def main(d: Path) -> None:
    ev_rows, comp = [], []
    for cycle, ymd in CYCLES.items():
        df = load(d, ymd)
        eday = pd.Timestamp(ELECTION_DAY[cycle])
        df = df[(df.date <= eday - pd.Timedelta(days=1)) & (df.date >= eday - pd.Timedelta(days=90))]
        b = pd.DataFrame({"date": df.date, "mode": "mail", "party": _party(df.voter_party_code),
                          "age_bin": _age_bin(df.age), "race5": "other"})
        cum = cumulate(b, "NC", cycle)
        cum = cum[(cum.age_bin == "all") & (cum.race5 == "all") & (cum["mode"] == "total")]  # party + total marginals only
        cum["days_out"] = cum.days_out.astype(int)
        ev_rows.append(cum[cum.days_out >= 1][EV_COLUMNS])
        if cycle == 2024:  # electorate party-by-group proxy: 2024 accepted early/absentee ballots (see note in report)
            r = df.race.str.upper().str.strip()
            hisp = df.ethnicity.str.upper().str.startswith("HISPANIC", na=False)
            g = pd.Series("other", index=df.index)
            g[r.eq("WHITE")], g[r.str.startswith("BLACK")], g[r.eq("ASIAN")] = "white", "black", "asian"
            g[hisp] = "hispanic"
            t = pd.DataFrame({"group": g, "party": _party(df.voter_party_code)}).value_counts().reset_index(name="count")
            wh = t[t.group == "white"]
            for grp in ("wnh_college", "wnh_noncollege"):
                comp.append(wh.assign(group=grp))
            comp.append(t[t.group != "white"])
    ev = pd.concat(ev_rows, ignore_index=True)
    ev.to_csv(ROOT / "data" / "manual" / "early_vote_NC.csv", index=False)
    fin = pd.DataFrame([dict(state_po="NC", cycle=c, party=p, age_bin="all", race5="all", final_ballots=v,
                             source_url=SRC.format(y=c)) for c, m in FINAL.items() for p, v in m.items()])
    path = ROOT / "data" / "manual" / "ev_final.csv"
    old = pd.read_csv(path) if path.exists() and path.stat().st_size > 60 else pd.DataFrame(columns=fin.columns)
    old = old[old.state_po != "NC"]
    pd.concat([old, fin], ignore_index=True).to_csv(path, index=False)
    pg = pd.concat(comp, ignore_index=True).assign(state_po="NC")[["state_po", "group", "party", "count"]]
    pg["source_url"] = "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2024_11_05/absentee_20241105.zip (2024 accepted early/absentee ballots; white split evenly college/non-college: PROXY)"
    path = ROOT / "data" / "manual" / "ev_party_group.csv"
    old = pd.read_csv(path) if path.exists() and path.stat().st_size > 40 else pd.DataFrame(columns=pg.columns)
    pd.concat([old[old.state_po != "NC"], pg], ignore_index=True).to_csv(path, index=False)
    print(ev.groupby(["cycle", "party"]).ballots.max().unstack())


if __name__ == "__main__":
    main(Path(sys.argv[1]))
