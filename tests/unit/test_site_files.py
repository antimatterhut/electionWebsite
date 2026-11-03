"""export/site_files.py: artifacts carry every key the site (types.ts) requires, and the validator catches gaps."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from senate.config import load_config
from senate.export import site_files as sf
from senate.export.publish import OVERLAY_RENAMES, publish

COMPONENTS = {"national": 12.0, "state_poll": 10.0, "market": None, "market_weight": 0.0, "state_swing": 11.0,
              "turnout": -0.5, "early_vote": 0.0}


def _summary() -> dict:
    race = {"state": "AL", "class": 2, "special": False, "incumbent": "X", "incumbent_party": "R",
            "dside": {"name": None, "party": "D"}, "rside": {"name": "Y", "party": "R"}, "rcv": False,
            "pres2024_margin": -30.0, "proj_margin": -19.5, "shift": 11.0, "swing_source": "combined",
            "components": dict(COMPONENTS), "polls": {"n": 4, "avg_margin": -18.0, "n_eff": 4.0},
            "p_dside_win": 0.01, "interval80": [-25.0, -13.0]}
    return {"run_id": "r1", "as_of": "2026-11-03", "model_version": "t", "weights": {"national": 2, "state_poll": 1},
            "national": {"generic_ballot": {"margin": 9.0, "n_polls": 5, "n_eff": 0.0, "se": None, "source": "x"},
                         "npv2024": -3.0, "s_nat": 12.0}, "races": [race]}


def _sim() -> dict:
    return {"seats": {"pmf": {"50": 0.4, "51": 0.6, "52": 1e-5}, "median": 51.0, "interval80": [50.0, 51.0],
                      "p_control": 0.6, "threshold": 51.0},
            "states": {"AL": {"m_hat": -19.5, "lo": -25.0, "hi": -13.0, "p_dside_win": 0.01}}}


def _counties(with_interval: bool) -> pd.DataFrame:
    return pd.DataFrame({"geoid": ["01001", "01003"], "name": ["A", "B"], "m0": [-40.0, -20.0], "m_hat": [-28.0, -9.0],
                         "omega": [1000.0, 3000.0], "votes_2024": [1200, 3500],
                         "lo": [-33.0, -14.0] if with_interval else [np.nan] * 2,
                         "hi": [-23.0, -4.0] if with_interval else [np.nan] * 2,
                         "p_dside_win": [0.0, 0.01] if with_interval else [np.nan] * 2, "county_method": ["uniform"] * 2})


def _write_tree(tmp_path, interval=True):
    sm = sf.augment_summary(_summary(), _sim(), {"AL": "none"}, {"AL": "fallback"}, {"AL": "uniform"})
    audit = pd.DataFrame({"pollster": ["P"], "field_end": ["2026-10-30"], "n": [np.nan], "pop": ["LV"], "margin": [-9.0]})
    shares = pd.DataFrame({g: [0.2, 0.2] for g in sf.GROUPS}, index=["01001", "01003"])
    doc = sf.build_state_file("AL", _counties(interval), _sim()["states"]["AL"], "r1", "2026-11-03", shares, audit, None, True)
    (tmp_path / "states").mkdir()
    (tmp_path / "states" / "AL.json").write_text(json.dumps(doc, allow_nan=False))
    (tmp_path / "summary.json").write_text(json.dumps(sm, allow_nan=False))
    rows = [[c["geoid"], c["pres2024_margin"], c["proj_margin"], c["shift"], c["p_dside_win"]] for c in doc["counties"]]
    (tmp_path / "counties_national.json").write_text(json.dumps({"cols": ["geoid", "pres2024", "proj", "shift", "p"], "rows": rows}))
    (tmp_path / "methodology_params.json").write_text(json.dumps(sf.methodology_params(load_config())))
    health = sf.site_data_health({"stages": {"fetch_pres": {"ok": True}, "fetch_x": {"ok": False}}}, "r1", "2026-11-03", ["f"])
    (tmp_path / "site_data_health.json").write_text(json.dumps(health))
    return doc


def test_artifacts_match_site_keys(tmp_path):
    _write_tree(tmp_path)
    sf.validate_site_files(tmp_path)
    s = json.loads((tmp_path / "summary.json").read_text())
    assert s["mock"] is False and s["races"][0]["name"] == "Alabama" and s["races"][0]["ei_status"] == "fallback"
    assert s["national"]["senate"]["distribution"] == {"50": 0.4, "51": 0.6}  # tiny cells dropped
    assert s["races"][0]["shift"] == 11.0  # model's state swing, untouched by the exporter


def test_state_band_fallback_for_counties_without_sim_interval(tmp_path):
    doc = _write_tree(tmp_path, interval=False)
    c = doc["counties"][0]
    assert c["interval80"] == [-33.5, -21.5] and "interval_from_state_band" in c["flags"]
    assert 0 <= c["p_dside_win"] <= 1
    sf.validate_site_files(tmp_path)


def test_validator_rejects_missing_keys(tmp_path):
    _write_tree(tmp_path)
    p = tmp_path / "states" / "AL.json"
    d = json.loads(p.read_text())
    del d["counties"][0]["interval80"]
    p.write_text(json.dumps(d))
    with pytest.raises(AssertionError):
        sf.validate_site_files(tmp_path)


def test_site_data_health_shape():
    h = sf.site_data_health({"stages": {"a": {"ok": True}, "b": {"ok": False}}}, "r", "d", ["flag"])
    assert [x["status"] for x in h["sources"]] == ["ok", "stale"] and h["flags"] == ["flag"]


def test_polls_recent_sorted_and_capped():
    a = pd.DataFrame({"pollster": list("abcdefgh"), "field_end": [f"2026-10-{d:02d}" for d in range(1, 9)],
                      "n": [500.0] * 8, "pop": ["LV"] * 8, "margin": [1.0] * 8})
    out = sf.polls_recent(a)
    assert len(out) == 6 and out[0]["pollster"] == "h" and set(out[0]) == sf.POLL_KEYS


def test_publish_renames_site_health(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    _write_tree(run)
    (run / "changes.json").write_text(json.dumps({"run_id": "r1", "as_of": "d", "items": []}))
    (run / "data_health.json").write_text(json.dumps({"stages": {}}))  # pipeline-internal, must not be published
    assert OVERLAY_RENAMES == {"site_data_health.json": "data_health.json"}
    dest = publish(run, None, tmp_path / "dest")
    assert "sources" in json.loads((dest / "data_health.json").read_text())
