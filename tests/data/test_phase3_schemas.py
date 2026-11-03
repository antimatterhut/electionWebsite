"""pandera checks for the Phase 3 tables (plan §11.3 conventions)."""
from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
import pytest

from senate.ei.groups import GROUPS
from senate.schemas import SCHEMAS, ei_group_vote, group_swing

PROV = {"source": "t", "retrieved_at": pd.Timestamp("2026-11-02", tz="UTC"), "data_quality_flag": "ok"}


def _ei(**over):
    rows = [{"geoid": "13001", "group": g, "theta_mean": 0.5, "theta_p10": 0.4, "theta_p90": 0.6, "n_group": 10.0,
             "ei_status": "ok", "rhat_max": 1.0, "ess_min": 500.0, **PROV} for g in GROUPS]
    return pd.DataFrame(rows).assign(**over)


def test_ei_group_vote_accepts_valid():
    assert len(ei_group_vote.validate(_ei())) == 6


@pytest.mark.parametrize("bad", [{"theta_mean": 1.2}, {"ei_status": "meh"}, {"group": "martian"}, {"n_group": -1.0}])
def test_ei_group_vote_rejects(bad):
    with pytest.raises(pa.errors.SchemaError):
        ei_group_vote.validate(_ei(**bad))


def test_ei_group_vote_rejects_inverted_interval_and_duplicates():
    with pytest.raises(pa.errors.SchemaError):
        ei_group_vote.validate(_ei(theta_p10=0.7))
    with pytest.raises(pa.errors.SchemaError):
        ei_group_vote.validate(pd.concat([_ei(), _ei()], ignore_index=True))


def test_group_swing_schema():
    ok = pd.DataFrame([{"region": "south", "group": g, "delta_mean": 9.0, "delta_sd": 4.0, "n_polls": 0,
                        "shrinkage_factor": 1.0, **PROV} for g in GROUPS])
    assert len(group_swing.validate(ok)) == 6
    with pytest.raises(pa.errors.SchemaError):
        group_swing.validate(ok.assign(delta_sd=-1.0))
    assert {"ei_group_vote", "ei_shift_2024", "group_swing"} <= set(SCHEMAS)
