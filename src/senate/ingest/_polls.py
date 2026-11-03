"""Shared poll-table normalisation for Wikipedia scrapes (plan §4.2-4.3)."""
from __future__ import annotations

import hashlib
import io
import re
from datetime import date

import pandas as pd

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
POP_ORDER = ["LV", "RV", "A"]


def parse_date_range(text: str, default_year: int) -> tuple[date | None, date | None]:
    """'Oct 20–23, 2026', 'Oct 28 – Nov 2, 2026', 'Oct 25, 2026' -> (start, end)."""
    t = re.sub(r"\[.*?\]", "", str(text)).replace("–", "-").replace("—", "-").replace(",", " ")
    toks = re.findall(r"[A-Za-z]{3,}\.?|\d+", t)
    year = next((int(x) for x in toks if len(x) == 4 and x.isdigit()), default_year)
    parts: list[tuple[int, int]] = []
    month = None
    for x in toks:
        k = x[:3].lower().rstrip(".")
        if not x.isdigit() and k in MONTHS:
            month = MONTHS[k]
        elif x.isdigit() and len(x) <= 2 and month:
            parts.append((month, int(x)))
    if not parts:
        return None, None
    return date(year, *parts[0]), date(year, *parts[-1])


def parse_sample(text: str) -> tuple[int | None, str | None]:
    """'1,200 (LV)' -> (1200, 'LV'); '800 RV'; '1000 A'."""
    t = str(text)
    m = re.search(r"(\d[\d,]*)", t)
    n = int(m.group(1).replace(",", "")) if m else None
    pop = next((c for c in ("LV", "RV", "A") if re.search(rf"\b{c}\b", t)), None)
    if pop is None and re.search(r"adults", t, re.I):
        pop = "A"
    return n, pop


def parse_pct(x) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", re.sub(r"\[.*?\]", "", str(x)))
    return float(m.group(1)) if m else None


def make_poll_id(pollster: str, field_end, n, pop) -> str:
    return hashlib.sha1(f"{pollster}|{field_end}|{n}|{pop}".encode()).hexdigest()[:12]


def apply_aliases(series: pd.Series, aliases: pd.DataFrame) -> pd.Series:
    return series.replace(dict(zip(aliases.alias, aliases.canonical, strict=True)))


def dedupe_polls(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate (poll_id, pop) rows; order LV > RV > A so the preferred population survives."""
    d = df.copy()
    d["_p"] = d["pop"].map({p: i for i, p in enumerate(POP_ORDER)})
    return d.sort_values("_p").drop_duplicates(["poll_id", "pop"]).drop(columns="_p").reset_index(drop=True)


def drop_overlapping_trackers(df: pd.DataFrame, gap_days: int, group_cols: list[str]) -> pd.DataFrame:
    """Keep one release per pollster per `gap_days` window when releases overlap (tracking polls)."""
    keep = []
    for _, g in df.sort_values("field_end").groupby(group_cols + ["pollster"]):
        last_end = None
        for idx, r in g.iterrows():
            if last_end is None or (r.field_end - last_end).days >= gap_days:
                keep.append(idx)
                last_end = r.field_end
    return df.loc[sorted(keep)].reset_index(drop=True)


_SPAN = re.compile(r"""(rowspan|colspan)\s*=\s*["']?(\d+)[^\d\s>]*""", re.I)


def _fix_span(m: re.Match) -> str:
    return f'{m.group(1)}="{m.group(2)}"'


def read_html_tables(html: str) -> list[pd.DataFrame]:
    """pd.read_html after repairing malformed span attributes (e.g. rowspan="2"" on the FL page)."""
    return pd.read_html(io.StringIO(_SPAN.sub(_fix_span, html)))


_FOOTNOTE = re.compile(r"\[[^\]]*\]")
_PARTY_TAG = re.compile(r"\s*\(([RD])\)\s*$")


def clean_pollster(raw: str) -> tuple[str, bool]:
    """'InsiderAdvantage (R)[124]' -> ('InsiderAdvantage', True): strip footnotes, flag party-tagged sponsors."""
    name = _FOOTNOTE.sub("", str(raw)).strip()
    m = _PARTY_TAG.search(name)
    return (_PARTY_TAG.sub("", name).strip(), True) if m else (name, False)
