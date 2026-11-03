"""Generic-ballot raw polls from Wikipedia (plan §4.2). Aggregators are diagnostics only (manual headlines)."""
from __future__ import annotations


import pandas as pd

from ..io import Fetcher
from . import _polls as P
from ._base import manual_dir, processed_dir, stamp, with_fallback, write_parquet

# The dedicated "Opinion polling for the 2026 ... House" page named in plan §4.2 returns 404 (checked 2026-11-02) and
# the page below carries only an aggregator summary table, so in practice this stage falls back to
# data/manual/generic_polls.csv until a raw-poll source is chosen.
WIKI_URL = "https://en.wikipedia.org/wiki/2026_United_States_House_of_Representatives_elections"
COLUMNS = ["poll_id", "pollster", "sponsor", "field_start", "field_end", "n", "pop", "mode",
           "d_pct", "r_pct", "und_pct", "partisan", "source_url"]


def _find(cols: list[str], *needles: str) -> str | None:
    for c in cols:
        if any(n in c.lower() for n in needles):
            return c
    return None


def flatten_columns(t: pd.DataFrame) -> pd.DataFrame:
    t = t.copy()
    t.columns = [" ".join(dict.fromkeys(map(str, c))).strip() if isinstance(c, tuple) else str(c)
                 for c in t.columns]
    return t


def normalize_generic_table(tbl: pd.DataFrame, default_year: int, aliases: pd.DataFrame | None = None
                            ) -> pd.DataFrame:
    """One Wikipedia poll table -> generic_polls schema (rows without D and R shares are dropped)."""
    t = flatten_columns(tbl)
    cols = list(t.columns)
    c_poll = _find(cols, "poll source", "pollster")
    c_date = _find(cols, "date")
    c_n = _find(cols, "sample")
    c_d = _find(cols, "democrat")
    c_r = _find(cols, "republican")
    c_u = _find(cols, "undecided")
    c_mode = _find(cols, "mode", "method")
    if not all([c_poll, c_date, c_d, c_r]):
        return pd.DataFrame(columns=COLUMNS)
    rows = []
    for _, r in t.iterrows():
        d, rep = P.parse_pct(r[c_d]), P.parse_pct(r[c_r])
        s, e = P.parse_date_range(r[c_date], default_year)
        if d is None or rep is None or e is None:
            continue
        n, pop = P.parse_sample(r[c_n]) if c_n else (None, None)
        pollster, partisan = P.clean_pollster(r[c_poll])
        rows.append({
            "pollster": pollster, "sponsor": "", "field_start": s, "field_end": e, "n": n,
            "pop": pop or "A", "mode": str(r[c_mode]) if c_mode else "",
            "d_pct": d, "r_pct": rep, "und_pct": P.parse_pct(r[c_u]) if c_u else None,
            "partisan": partisan, "source_url": WIKI_URL,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=COLUMNS)
    if aliases is not None and len(aliases):
        out["pollster"] = P.apply_aliases(out.pollster, aliases)
    out["poll_id"] = [P.make_poll_id(a, b, c, d) for a, b, c, d in zip(out.pollster, out.field_end, out.n, out["pop"])]
    out["n"] = out.n.astype("Int64")
    return P.dedupe_polls(out)[COLUMNS]


def _load_aliases() -> pd.DataFrame:
    p = manual_dir() / "pollster_aliases.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame(columns=["alias", "canonical"])


def _scrape(fetcher: Fetcher, year: int) -> pd.DataFrame:
    html = fetcher.get(WIKI_URL, "wikipedia_generic").decode("utf-8", "replace")
    aliases = _load_aliases()
    frames = [normalize_generic_table(t, year, aliases) for t in P.read_html_tables(html)]
    frames = [f for f in frames if len(f)]
    if not frames:
        raise ValueError("no poll tables parsed from Wikipedia page")
    return P.dedupe_polls(pd.concat(frames, ignore_index=True))


def ingest_generic_polls(fetcher: Fetcher | None = None, year: int = 2026, allow_fallback: bool = True
                         ) -> pd.DataFrame:
    own = fetcher is None
    fetcher = fetcher or Fetcher()
    try:
        df = with_fallback("generic_ballot", lambda: stamp(_scrape(fetcher, year), "wikipedia", "live"),
                           manual_dir() / "generic_polls.csv", allow_fallback,
                           read_kwargs={"parse_dates": ["field_start", "field_end"]})
        write_parquet(df, processed_dir() / "generic_polls.parquet")
        return df
    finally:
        if own:
            fetcher.close()
