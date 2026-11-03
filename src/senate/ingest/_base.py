"""Shared ingest plumbing: provenance columns and the manual-fallback wrapper (plan §4 global policy)."""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import structlog

from ..config import ROOT
from ..io import utcnow

log = structlog.get_logger()


def _dir(env: str, default: str) -> Path:
    return Path(os.environ.get(env, ROOT / "data" / default))


def manual_dir() -> Path:
    return _dir("SENATE_MANUAL_DIR", "manual")


def interim_dir() -> Path:
    return _dir("SENATE_INTERIM_DIR", "interim")


def processed_dir() -> Path:
    return _dir("SENATE_PROCESSED_DIR", "processed")


def stamp(df: pd.DataFrame, source: str, version: str, flag: str = "ok") -> pd.DataFrame:
    out = df.copy()
    out["source"] = source
    out["retrieved_at"] = utcnow()
    out["source_version"] = version
    out["data_quality_flag"] = flag
    return out


def with_fallback(name: str, fetch: Callable[[], pd.DataFrame], manual_csv: Path, allow_fallback: bool = True,
                  read_kwargs: dict | None = None) -> pd.DataFrame:
    """Run `fetch`; on any failure load `manual_csv`, stamped data_quality_flag='manual'."""
    try:
        df = fetch()
        log.info("source_fetch", source=name, status="ok", rows=len(df), fallback=False)
        return df
    except Exception as e:  # noqa: BLE001 - any fetch/parse failure triggers the fallback
        if not allow_fallback:
            raise
        log.warning("warning", code="FALLBACK_USED", source=name, fallback="manual", error=str(e)[:200])
        if not manual_csv.exists():
            raise FileNotFoundError(f"{name}: fetch failed and no manual fallback at {manual_csv}") from e
        df = pd.read_csv(manual_csv, dtype={"geoid": str, "county_fips": str}, **(read_kwargs or {}))
        df["source"] = f"manual:{manual_csv.name}"
        df["retrieved_at"] = utcnow()
        df["source_version"] = "manual"
        df["data_quality_flag"] = "manual"
        log.info("source_fetch", source=name, status="fallback", rows=len(df), fallback=True)
        return df


def write_parquet(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path
