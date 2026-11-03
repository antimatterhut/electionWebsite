"""Phase 7: diff report, previous-good publish fallback, results overlay."""
import json
import shutil

import pandas as pd
import pytest

from senate.export.diff import diff_runs, write_diff
from senate.export.publish import PublishError, publish
from senate.ingest.results_overlay import build_overlay


def _summary(margin=-5.0, s_nat=8.0, p=0.30, run="r1"):
    return {"run_id": run, "as_of": "2026-11-02", "national": {"s_nat": s_nat, "generic_ballot": {"margin": 7.0}},
            "races": [{"state": "OH", "proj_margin": margin, "p_dside_win": p, "swing_source": "combined",
                       "polls": {"n": 3}, "components": {"early_vote": 0.0}}]}


def _write(d, summary, health=None):
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps(summary))
    (d / "changes.json").write_text("{}")
    (d / "data_health.json").write_text(json.dumps(health or {"sources": [{"name": "polls", "status": "ok"}]}))
    return d


def test_diff_flags_alerts(cfg, tmp_path):
    prev, new = _write(tmp_path / "p", _summary()), _write(tmp_path / "n", _summary(margin=-3.5, p=0.40, run="r2"),
                                                           {"sources": [{"name": "polls", "status": "fallback"}]})
    rep = diff_runs(prev, new, cfg)
    assert rep.alerts == 1 and "⚠️" in rep.markdown and "polls: fallback" in rep.markdown
    assert rep.changes["items"][0]["state"] == "OH"
    write_diff(rep, tmp_path / "o")
    assert (tmp_path / "o" / "diff.md").exists() and json.loads((tmp_path / "o" / "changes.json").read_text())["run_id"] == "r2"


def test_diff_without_previous(cfg, tmp_path):
    rep = diff_runs(None, _write(tmp_path / "n", _summary()), cfg)
    assert rep.alerts == 0 and "No previous" in rep.markdown


def test_publish_swaps_and_carries_over(tmp_path):
    dest = _write(tmp_path / "live", _summary(run="old"))
    (dest / "counties_national.json").write_text("{}")
    run = _write(tmp_path / "run", _summary(run="new"))
    snap = tmp_path / "snap"
    shutil.copytree(dest, snap)
    publish(run, snap, dest)
    assert json.loads((dest / "summary.json").read_text())["run_id"] == "new"
    assert (dest / "counties_national.json").exists()  # carried over from previous-good


@pytest.mark.parametrize("bad", [_summary(margin=250.0), _summary(p=1.5), {**_summary(), "races": []}, {**_summary(), "mock": True}])
def test_publish_rejects_bad_run_and_keeps_previous(tmp_path, bad):
    dest = _write(tmp_path / "live", _summary(run="old"))
    run = _write(tmp_path / "run", bad)
    with pytest.raises(PublishError):
        publish(run, dest, dest)
    assert json.loads((dest / "summary.json").read_text())["run_id"] == "old"
    assert not (tmp_path / "live.staging").exists()


def test_overlay_off_and_on(cfg, tmp_path):
    assert build_overlay(cfg) is None
    p = tmp_path / "r.csv"
    pd.DataFrame({"geoid": ["39001", "39003"], "votes_d": [100, 300], "votes_r": [300, 100], "pct_reporting": [95, 99]}).to_csv(p, index=False)
    cfg.results.mode = "overlay"
    o = build_overlay(cfg, p)
    assert o["states"]["OH"]["margin"] == 0.0 and o["states"]["OH"]["show_actual"]
    pd.DataFrame({"geoid": ["39001"], "votes_d": [1], "votes_r": [1], "pct_reporting": [120]}).to_csv(p, index=False)
    with pytest.raises(ValueError):
        build_overlay(cfg, p)
