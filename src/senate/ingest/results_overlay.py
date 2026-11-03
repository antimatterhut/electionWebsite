"""Election-night results overlay (plan §8.6). Manual CSV only: data/manual/results_2026.csv.

Columns: geoid, votes_d, votes_r, pct_reporting. No automated scraping of news/AP results. With
`config.results.mode == "off"` nothing is written. The overlay never replaces the projection; the UI shows
“Actual vs projected” once a state is >= 90% reporting."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..config import Settings
from ..geo.fips import FIPS_STATE
from ._base import manual_dir

THRESHOLD = 90.0


def build_overlay(cfg: Settings, path: Path | None = None) -> dict | None:
    if cfg.results.mode != "overlay":
        return None
    path = path or manual_dir() / "results_2026.csv"
    if not path.exists():
        raise FileNotFoundError(f"results.mode=overlay but {path} is missing")
    df = pd.read_csv(path, dtype={"geoid": str})
    missing = {"geoid", "votes_d", "votes_r", "pct_reporting"} - set(df.columns)
    if missing:
        raise ValueError(f"results csv missing columns {sorted(missing)}")
    if (df[["votes_d", "votes_r"]] < 0).any().any() or not df.pct_reporting.between(0, 100).all():
        raise ValueError("results csv has negative votes or pct_reporting outside 0-100")
    df["geoid"] = df.geoid.str.zfill(5)
    df["state"] = df.geoid.str[:2].map(FIPS_STATE)
    counties = [{"geoid": r.geoid, "state": r.state, "votes_d": int(r.votes_d), "votes_r": int(r.votes_r),
                 "pct_reporting": float(r.pct_reporting)} for r in df.itertuples()]
    states = {}
    for s, g in df.groupby("state"):
        two = g.votes_d.sum() + g.votes_r.sum()
        pct = float(g.pct_reporting.mean())  # unweighted: the CSV carries no expected-vote totals
        states[s] = {"votes_d": int(g.votes_d.sum()), "votes_r": int(g.votes_r.sum()), "pct_reporting": round(pct, 1),
                     "margin": round(100 * (g.votes_d.sum() - g.votes_r.sum()) / two, 2) if two else None,
                     "show_actual": bool(pct >= THRESHOLD)}
    return {"mode": "overlay", "threshold": THRESHOLD, "states": states, "counties": counties}


def write_overlay(cfg: Settings, out_dir: Path) -> Path | None:
    o = build_overlay(cfg)
    if o is None:
        return None
    p = Path(out_dir) / "results_overlay.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o), encoding="utf-8")
    return p
