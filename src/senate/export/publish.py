"""Validate a finished run and publish it with a previous-good fallback (plan §8.3, §8.5).

The published tree (`site/static/data`, kept on the `data` branch) is rebuilt in a staging directory: start from the
previous-good tree, overlay the files of the new run, validate, then swap. Any failure leaves the previous tree
untouched, so the live site never loses data."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

REQUIRED = ["summary.json", "changes.json", "data_health.json"]
# Files a run may provide; anything absent is carried over from the previous-good tree.
OVERLAY = ["summary.json", "changes.json", "diff.md", "backtest_summary.json",
           "methodology_params.json", "counties_national.json", "results_overlay.json"]
# output name -> published name. The pipeline's own output/data_health.json ({stages, tables, ...}) stays internal;
# the site reads the {sources, flags} version written by export/site_files.py.
OVERLAY_RENAMES = {"site_data_health.json": "data_health.json"}
OVERLAY_DIRS = ["states", "topo"]


class PublishError(RuntimeError):
    pass


def validate(tree: Path, expected_states: int | None = None) -> None:
    for f in REQUIRED:
        if not (tree / f).exists():
            raise PublishError(f"missing {f}")
    s = json.loads((tree / "summary.json").read_text(encoding="utf-8"))
    if s.get("mock"):
        raise PublishError("refusing to publish mock data")
    races = s.get("races") or []
    if not races or (expected_states and len(races) != expected_states):
        raise PublishError(f"summary.json has {len(races)} races (expected {expected_states or '>0'})")
    for r in races:
        m = r.get("proj_margin")
        if m is None or not -100 <= m <= 100:
            raise PublishError(f"{r.get('state')}: bad proj_margin {m!r}")
        p = r.get("p_dside_win")
        if p is not None and not 0 <= p <= 1:
            raise PublishError(f"{r.get('state')}: bad p_dside_win {p!r}")
    if (tree / "states").is_dir():
        for f in (tree / "states").glob("*.json"):
            json.loads(f.read_text(encoding="utf-8"))


def publish(run_dir: Path, prev_dir: Path | None, dest: Path, expected_states: int | None = None) -> Path:
    run_dir, dest = Path(run_dir), Path(dest)
    stage = dest.with_name(dest.name + ".staging")
    shutil.rmtree(stage, ignore_errors=True)
    if prev_dir and Path(prev_dir).is_dir():
        shutil.copytree(prev_dir, stage)
    else:
        stage.mkdir(parents=True)
    try:
        for f in OVERLAY:
            if (run_dir / f).exists():
                shutil.copy2(run_dir / f, stage / f)
        for src, dst in OVERLAY_RENAMES.items():
            if (run_dir / src).exists():
                shutil.copy2(run_dir / src, stage / dst)
        for d in OVERLAY_DIRS:
            if (run_dir / d).is_dir():
                shutil.copytree(run_dir / d, stage / d, dirs_exist_ok=True)
        validate(stage, expected_states)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    old = dest.with_name(dest.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    try:
        if dest.exists():
            dest.rename(old)
        stage.rename(dest)
    except PermissionError:
        # Windows refuses to rename a directory another process holds open (e.g. a running `vite dev` watching it):
        # restore it if the first rename went through, then replace its contents in place.
        if old.exists() and not dest.exists():
            old.rename(dest)
        for child in dest.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        shutil.copytree(stage, dest, dirs_exist_ok=True)
        shutil.rmtree(stage, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    return dest
