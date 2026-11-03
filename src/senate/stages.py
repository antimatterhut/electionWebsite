"""Fetch-stage definitions and the source-health report (plan §8.1, Phase 1 review artefacts)."""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import structlog

from .config import ROOT
from .ingest._base import manual_dir, processed_dir

log = structlog.get_logger()
CODE_VERSION = "phase1-0"
HASHES = ROOT / "data" / "cache" / "stage_hashes.json"
OUTPUT = ROOT / "output"


@dataclass
class Stage:
    name: str
    fn: Callable[[], object]
    outputs: list[str] = field(default_factory=list)
    code_version: str = CODE_VERSION


def _races() -> pd.DataFrame:
    df = pd.read_csv(manual_dir() / "races_2026.csv", keep_default_na=False)
    return df


def fetch_stages() -> list[Stage]:
    from .ingest import acs_cvap, crosstabs, generic_ballot, pres_results, senate_polls, shapes, validated_voter

    return [
        Stage("fetch_pres", pres_results.ingest_pres_results, ["pres_county.parquet"]),
        Stage("fetch_acs_cvap", acs_cvap.ingest_acs_cvap,
              ["cvap_county.parquet", "edu_county.parquet", "age_county.parquet"]),
        Stage("fetch_shapes", shapes.ingest_shapes, ["geographies.parquet"]),
        Stage("fetch_generic", generic_ballot.ingest_generic_polls, ["generic_polls.parquet"]),
        Stage("fetch_senate_polls", senate_polls.ingest_senate_polls, ["senate_polls.parquet"]),
        Stage("fetch_crosstabs", crosstabs.ingest_crosstabs, ["crosstabs.parquet"]),
        Stage("validated_priors", validated_voter.ingest_validated_voter, ["validated_voter_priors.parquet"]),
    ]


def _sha(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest() if path.exists() else ""


def data_health(stage_status: dict[str, dict]) -> dict:
    """output/data_health.json: per-source status, flags, row counts and county counts by state."""
    proc = processed_dir()
    tables = {}
    for p in sorted(proc.glob("*.parquet")):
        df = pd.read_parquet(p)
        flags = df["data_quality_flag"].value_counts().to_dict() if "data_quality_flag" in df else {}
        tables[p.stem] = {"rows": len(df), "flags": flags, "sha1": _sha(p)[:12]}
    counties: dict[str, int] = {}
    pc = proc / "pres_county.parquet"
    if pc.exists():
        d = pd.read_parquet(pc)
        counties = d[d.year == d.year.max()].groupby("state_po").size().to_dict()
    if not counties and (proc / "geographies.parquet").exists():  # pres results unavailable: count shapes instead
        g = pd.read_parquet(proc / "geographies.parquet")
        counties = g.groupby("state_po").size().to_dict()
    return {"stages": stage_status, "tables": tables, "counties_by_state": counties,
            "n_races": len(_races()) if (manual_dir() / "races_2026.csv").exists() else 0}


def run_fetch() -> int:
    """Run every fetch stage; a failing stage is recorded and makes the run exit non-zero."""
    status: dict[str, dict] = {}
    failed = 0
    for st in fetch_stages():
        t0 = time.time()
        log.info("stage_start", stage=st.name)
        try:
            st.fn()
            status[st.name] = {"ok": True, "seconds": round(time.time() - t0, 2)}
        except Exception as e:  # noqa: BLE001
            failed += 1
            status[st.name] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
            log.error("stage_failed", stage=st.name, error=str(e)[:300])
        log.info("stage_end", stage=st.name, seconds=round(time.time() - t0, 2), skipped=False)
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / "data_health.json").write_text(json.dumps(data_health(status), indent=2, default=str), encoding="utf-8")
    return 1 if failed else 0
