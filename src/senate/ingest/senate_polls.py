"""Senate race polls from per-state Wikipedia pages (plan §4.3)."""
from __future__ import annotations


import pandas as pd

from ..io import Fetcher
from . import _polls as P
from ._base import log, manual_dir, processed_dir, stamp, write_parquet
from .generic_ballot import _find, flatten_columns

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AR": "Arkansas", "CO": "Colorado", "DE": "Delaware", "FL": "Florida",
    "GA": "Georgia", "ID": "Idaho", "IL": "Illinois", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MT": "Montana", "NE": "Nebraska", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NC": "North Carolina", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "VA": "Virginia", "WV": "West Virginia", "WY": "Wyoming",
}
COLUMNS = ["poll_id", "state_po", "pollster", "sponsor", "field_start", "field_end", "n", "pop", "mode",
           "dside_pct", "rside_pct", "other_pct", "und_pct", "matchup_type", "partisan", "source_url"]


def wiki_url(state_po: str) -> str:
    name = STATE_NAMES[state_po].replace(" ", "_")
    return f"https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_{name}"


def _surname(name) -> str:
    return str(name).split()[-1].lower() if isinstance(name, str) and name.strip() else ""


def normalize_senate_table(tbl: pd.DataFrame, race: pd.Series, default_year: int, url: str,
                           aliases: pd.DataFrame | None = None, changes: pd.DataFrame | None = None
                           ) -> pd.DataFrame:
    """One state polling table -> senate_polls schema. D/R columns are found by nominee surname."""
    t = flatten_columns(tbl)
    cols = list(t.columns)
    d_sn, r_sn = _surname(race.get("dside_name")), _surname(race.get("rside_name"))
    c_d = next((c for c in cols if d_sn and d_sn in c.lower()), None)
    c_r = next((c for c in cols if r_sn and r_sn in c.lower()), None)
    c_poll, c_date, c_n = _find(cols, "poll source", "pollster"), _find(cols, "date"), _find(cols, "sample")
    c_u, c_mode = _find(cols, "undecided"), _find(cols, "mode", "method")
    if not all([c_d, c_r, c_poll, c_date]):
        return pd.DataFrame(columns=COLUMNS)
    skip = {c_d, c_r, c_poll, c_date, c_n, c_u, c_mode}
    skip |= {c for c in cols if "lead" in c.lower() or "margin" in c.lower()}
    other_cols = [c for c in cols if c not in skip]
    rows = []
    for _, r in t.iterrows():
        d, rep = P.parse_pct(r[c_d]), P.parse_pct(r[c_r])
        s, e = P.parse_date_range(r[c_date], default_year)
        if d is None or rep is None or e is None:
            continue
        pollster, partisan = P.clean_pollster(r[c_poll])
        oth_vals = [v for v in (P.parse_pct(r[c]) for c in other_cols) if v]
        n, pop = P.parse_sample(r[c_n]) if c_n else (None, None)
        rows.append({
            "state_po": race["state_po"], "pollster": pollster, "sponsor": "",
            "field_start": s, "field_end": e, "n": n, "pop": pop or "A", "mode": str(r[c_mode]) if c_mode else "",
            "dside_pct": d, "rside_pct": rep, "other_pct": sum(oth_vals) or None,
            "und_pct": P.parse_pct(r[c_u]) if c_u else None,
            "matchup_type": "multi" if oth_vals else "two_way",
            "partisan": partisan, "source_url": url,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=COLUMNS)
    if aliases is not None and len(aliases):
        out["pollster"] = P.apply_aliases(out.pollster, aliases)
    if changes is not None and len(changes):
        # polls fielded before a nominee swap, in a table headed by the old nominee, are dropped
        header = " ".join(cols).lower()
        for _, ch in changes[changes.state_po == race["state_po"]].iterrows():
            if _surname(ch.old_name) in header:
                out = out[out.field_end >= pd.to_datetime(ch.effective_date).date()]
    out["poll_id"] = [P.make_poll_id(f"{a}|{s}", b, c, d)
                      for a, s, b, c, d in zip(out.pollster, out.state_po, out.field_end, out.n, out["pop"])]
    return P.dedupe_polls(out)[COLUMNS]


def _scrape(fetcher: Fetcher, races: pd.DataFrame, year: int) -> pd.DataFrame:
    ap, cp = manual_dir() / "pollster_aliases.csv", manual_dir() / "nominee_changes.csv"
    aliases = pd.read_csv(ap) if ap.exists() else None
    changes = pd.read_csv(cp) if cp.exists() else None
    frames, failures = [], []
    for _, race in races.iterrows():
        url = wiki_url(race["state_po"])
        try:
            html = fetcher.get(url, "wikipedia_senate").decode("utf-8", "replace")
            tabs = P.read_html_tables(html)
        except Exception as e:  # noqa: BLE001
            failures.append(race["state_po"])
            log.warning("warning", code="STATE_POLL_FETCH_FAILED", state=race["state_po"], error=str(e)[:120])
            continue
        frames += [n for n in (normalize_senate_table(tb, race, year, url, aliases, changes) for tb in tabs)
                   if len(n)]
    if not frames:
        raise ValueError(f"no Senate poll tables parsed (failed fetches: {failures})")
    return dedupe_across_tables(pd.concat(frames, ignore_index=True))


def dedupe_across_tables(df: pd.DataFrame) -> pd.DataFrame:
    """The same poll appears in several tables of a state page (general, multi-way, ...): keep one row per
    (poll_id, pop), preferring the two-way nominee matchup."""
    order = {"two_way": 0, "rcv_final": 1, "multi": 2}
    d = df.assign(_o=df.matchup_type.map(order).fillna(9)).sort_values("_o", kind="stable")
    return d.drop_duplicates(["poll_id", "pop"]).drop(columns="_o").sort_index().reset_index(drop=True)


def ingest_senate_polls(states: list[str] | None = None, fetcher: Fetcher | None = None, year: int = 2026,
                        allow_fallback: bool = True) -> pd.DataFrame:
    """Scrape polls for `states` (default: all races in races_2026.csv); fallback data/manual/senate_polls.csv."""
    races = pd.read_csv(manual_dir() / "races_2026.csv", dtype=str, keep_default_na=False)
    if states:
        races = races[races.state_po.isin(states)]
    own = fetcher is None
    fetcher = fetcher or Fetcher()
    try:
        try:
            df = stamp(_scrape(fetcher, races, year), "wikipedia", "live")
        except Exception as e:  # noqa: BLE001
            if not allow_fallback:
                raise
            log.warning("warning", code="FALLBACK_USED", source="senate_polls", fallback="manual", error=str(e)[:200])
            df = pd.read_csv(manual_dir() / "senate_polls.csv", parse_dates=["field_start", "field_end"])
            df = stamp(df, "manual:senate_polls.csv", "manual", "manual")
        write_parquet(df, processed_dir() / "senate_polls.parquet")
        return df
    finally:
        if own:
            fetcher.close()
