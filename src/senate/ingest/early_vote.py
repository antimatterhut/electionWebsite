"""2026 early vote + historical days-out tables (plan §4.6).

Per-state adapters implement `fetch() -> raw` and `parse(raw) -> long-format rows`. The live file URLs/column names
below are UNVERIFIED (checked against no live file); any fetch or parse failure falls back to
`data/manual/early_vote_{state}.csv` (flag 'manual'), which may also carry historical cycles (`cycle` column).

Long format (`EV_COLUMNS`): one row per (state, geoid|null, date, mode, party, age_bin, race5, cycle); `ballots` is the
CUMULATIVE count to that date. Only marginals are stored: exactly one of party/age_bin/race5 is not 'all'
(or none, for totals), so a category dimension is always unambiguous. mode-specific rows exist for totals only.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ..io import Fetcher
from ._base import log, manual_dir, processed_dir, stamp, with_fallback, write_parquet

EV_COLUMNS = ["state_po", "geoid", "date", "days_out", "mode", "party", "age_bin", "race5", "ballots", "cycle"]
KEY = ["state_po", "geoid", "date", "mode", "party", "age_bin", "race5", "cycle"]
ELECTION_DAY = {2018: date(2018, 11, 6), 2020: date(2020, 11, 3), 2022: date(2022, 11, 8),
                2024: date(2024, 11, 5), 2026: date(2026, 11, 3)}
# Order = build priority (plan Phase 4): NC, GA, FL first, then the rest as available.
EV_STATES = ["NC", "GA", "FL", "AZ", "NV", "MI", "PA", "OH", "TX", "WI"]
AGE_BINS = [(18, 29, "18-29"), (30, 44, "30-44"), (45, 64, "45-64"), (65, 200, "65+")]


def _party(code: pd.Series) -> pd.Series:
    c = code.astype(str).str.strip().str.upper().str[:3]
    return pd.Series(np.select([c.isin(["DEM", "D"]), c.isin(["REP", "R"]), c.isin(["UNA", "UNK", "U", "NPA", "IND", "NAN", ""])],
                               ["D", "R", "U"], "O"), index=code.index)


def _race5(code: pd.Series) -> pd.Series:
    c = code.astype(str).str.strip().str.upper()
    out = np.select([c.str.startswith(("W", "WHITE")), c.str.startswith(("B", "BLACK")),
                     c.str.startswith(("H", "HISP", "LAT")), c.str.startswith(("A", "ASIAN"))],
                    ["white", "black", "hispanic", "asian"], "other")
    return pd.Series(out, index=code.index)


def _age_bin(age: pd.Series) -> pd.Series:
    a = pd.to_numeric(age, errors="coerce")
    out = pd.Series("unknown", index=age.index)
    for lo, hi, lab in AGE_BINS:
        out[(a >= lo) & (a <= hi)] = lab
    return out


def _cum_rows(g: pd.DataFrame, eday: date, geoid, dim: str | None, val, mode: str) -> pd.DataFrame:
    days = pd.date_range(g.date.min(), eday, freq="D").date
    s = g.groupby("date").size().reindex(days, fill_value=0).cumsum()
    row = pd.DataFrame({"date": s.index, "ballots": s.to_numpy()})
    row["geoid"], row["mode"] = geoid, mode
    for k in ("party", "age_bin", "race5"):
        row[k] = val if k == dim else "all"
    return row


def cumulate(ballots: pd.DataFrame, state_po: str, cycle: int) -> pd.DataFrame:
    """Per-ballot frame (date, mode, party, age_bin, race5, geoid?) -> cumulative long-format marginals."""
    eday = ELECTION_DAY[cycle]
    b = ballots.copy()
    b["date"] = pd.to_datetime(b["date"]).dt.date
    b = b[b.date <= eday]
    has_geo = "geoid" in b and b.geoid.notna().any()
    parts = [_cum_rows(b, eday, None, None, "all", "total")]
    for mode in ("mail", "early_in_person"):
        if (b["mode"] == mode).any():
            parts.append(_cum_rows(b[b["mode"] == mode], eday, None, None, "all", mode))
    for dim in ("party", "age_bin", "race5"):
        for val, g in b.groupby(dim):
            parts.append(_cum_rows(g, eday, None, dim, val, "total"))
    if has_geo:
        for geo, g in b.dropna(subset=["geoid"]).groupby("geoid"):
            parts.append(_cum_rows(g, eday, geo, None, "all", "total"))
    out = pd.concat(parts, ignore_index=True)
    out["state_po"], out["cycle"] = state_po, cycle
    out["days_out"] = out.date.map(lambda d: (eday - d).days)
    return out[EV_COLUMNS]


class StateAdapter:
    """Base adapter: subclasses set `url`/`colmap` and may override fetch/parse."""
    state_po = ""
    url = ""
    colmap: dict[str, str] = {}   # canonical -> source column: date, party, age, race, mode?, geoid?
    mode_default = "mail"

    def fetch(self, fetcher: Fetcher, cycle: int) -> bytes:
        e = ELECTION_DAY[cycle]
        return fetcher.get(self.url.format(cycle=cycle, ymd=e.strftime("%Y%m%d"), y=e.strftime("%Y"), m=e.strftime("%m"),
                                           d=e.strftime("%d")),
                           f"early_vote_{self.state_po}")

    def parse(self, raw: bytes | pd.DataFrame, cycle: int) -> pd.DataFrame:
        import io
        if isinstance(raw, pd.DataFrame):
            df = raw
        elif raw[:2] == b"PK":  # zipped single CSV (NC)
            df = pd.read_csv(io.BytesIO(raw), dtype=str, compression="zip", encoding="latin-1")
        else:
            df = pd.read_csv(io.BytesIO(raw), dtype=str, sep=None, engine="python", encoding="latin-1")
        df.columns = [c.strip().lower() for c in df.columns]
        miss = [v for k, v in self.colmap.items() if k in ("date", "party") and v not in df]
        if miss:
            raise ValueError(f"{self.state_po}: expected columns missing {miss} (layout changed?)")
        c = self.colmap
        out = pd.DataFrame({"date": pd.to_datetime(df[c["date"]], errors="coerce")})
        out["party"] = _party(df[c["party"]])
        out["age_bin"] = _age_bin(df[c["age"]]) if c.get("age") in df else "unknown"
        out["race5"] = _race5(df[c["race"]]) if c.get("race") in df else "other"
        out["mode"] = df[c["mode"]].map(self.mode_map).fillna(self.mode_default) if c.get("mode") in df else self.mode_default
        if c.get("geoid") in df:
            out["geoid"] = df[c["geoid"]].astype(str).str.zfill(5)
        if c.get("status") in df:  # only accepted ballots count (spoiled/cancelled/pending rows carry return dates too)
            out = out[df[c["status"]].astype(str).str.upper().str.startswith("ACCEPT").to_numpy()]
        out = out.dropna(subset=["date"])
        # final pre-election totals: nothing from election day itself (days_out >= 1), and no typo'd future dates
        out = out[out.date <= pd.Timestamp(ELECTION_DAY[cycle]) - pd.Timedelta(days=1)]
        if out.empty:
            raise ValueError(f"{self.state_po}: no returned ballots parsed")
        cum = cumulate(out, self.state_po, cycle)
        return cum[cum.days_out >= 1].reset_index(drop=True)  # final pre-election totals only

    mode_map: dict[str, str] = {}


class NC(StateAdapter):
    state_po = "NC"
    url = "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/{y}_{m}_{d}/absentee_{ymd}.zip"  # verified 2026-11-03 (200 for 2022/24/26)
    colmap = {"date": "ballot_rtn_dt", "party": "voter_party_code", "age": "age", "race": "race",
              "status": "ballot_rtn_status"}


class GA(StateAdapter):
    state_po = "GA"
    url = "https://mvp.sos.ga.gov/absentee/{ymd}.csv"  # UNVERIFIED path
    colmap = {"date": "ballot return date", "party": "party", "age": "age", "race": "race"}


class FL(StateAdapter):
    state_po = "FL"
    url = "https://dos.fl.gov/elections/data-statistics/{ymd}.csv"  # UNVERIFIED path
    colmap = {"date": "ballot_receive_date", "party": "party", "age": "age", "race": "race"}


ADAPTERS: dict[str, StateAdapter] = {a.state_po: a for a in (NC(), GA(), FL())}


def _read_manual_state(state_po: str) -> pd.DataFrame:
    p = manual_dir() / f"early_vote_{state_po}.csv"
    if not p.exists():
        raise FileNotFoundError(p)
    return pd.read_csv(p, dtype={"geoid": str})


def ingest_state_ev(state_po: str, cycle: int = 2026, fetcher: Fetcher | None = None,
                    allow_fallback: bool = True) -> pd.DataFrame:
    """Adapter -> long format for `cycle`; states without an adapter use the manual CSV only."""
    manual = manual_dir() / f"early_vote_{state_po}.csv"

    def _fetch() -> pd.DataFrame:
        ad = ADAPTERS.get(state_po)
        if ad is None:
            raise NotImplementedError(f"no adapter for {state_po}")
        f = fetcher or Fetcher()
        return ad.parse(ad.fetch(f, cycle), cycle)

    df = with_fallback(f"early_vote_{state_po}", _fetch, manual, allow_fallback)
    if "cycle" in df:
        df = df[df.cycle == cycle]
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def _combine(parts: list[pd.DataFrame], prior: pd.DataFrame | None) -> pd.DataFrame:
    cols = EV_COLUMNS + [c for c in ("source", "retrieved_at", "source_version", "data_quality_flag") if parts and c in parts[0]]
    new = pd.concat([p for p in parts if len(p)], ignore_index=True) if parts else pd.DataFrame(columns=cols)
    if prior is not None and len(prior):
        new = pd.concat([prior, new], ignore_index=True)
    if len(new):
        new["geoid"] = new["geoid"].where(new["geoid"].notna(), None)
        new = new.drop_duplicates(KEY, keep="last").sort_values(["state_po", "cycle", "date"]).reset_index(drop=True)
    return new


def ingest_early_vote(states: list[str] | None = None, fetcher: Fetcher | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Append today's 2026 snapshot to early_vote_daily and rebuild early_vote_hist from manual files.

    A state with no source at all is skipped (ev_detail 'none'); this never fails the fetch stage."""
    from ..schemas import SCHEMAS

    proc = processed_dir()
    daily_parts, hist_parts = [], []
    for st in (states or EV_STATES):
        try:
            d = ingest_state_ev(st, 2026, fetcher)
            if len(d):
                daily_parts.append(d if "source" in d else stamp(d, f"adapter:{st}", "live"))
        except Exception as e:  # noqa: BLE001
            log.warning("warning", code="EV_NO_DATA", state=st, error=str(e)[:200])
        try:
            m = _read_manual_state(st)
            if "cycle" in m:
                h = m[m.cycle != 2026].copy()
                h["date"] = pd.to_datetime(h["date"]).dt.date
                if len(h):
                    hist_parts.append(stamp(h[EV_COLUMNS], f"manual:early_vote_{st}.csv", "manual", "manual"))
        except FileNotFoundError:
            pass
    daily_p = proc / "early_vote_daily.parquet"
    prior = pd.read_parquet(daily_p) if daily_p.exists() else None
    daily = _combine(daily_parts, prior)
    hist = _combine(hist_parts, None)
    for name, df in (("early_vote_daily", daily), ("early_vote_hist", hist)):
        if len(df):
            SCHEMAS[name].validate(df)
        write_parquet(df, proc / f"{name}.parquet")
    log.info("source_fetch", source="early_vote", status="ok", rows=len(daily), hist_rows=len(hist))
    return daily, hist
