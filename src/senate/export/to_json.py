"""Minimal `summary.json` (plan §9.1) for Phase 2: national swing and the per-race state projection.

Fields owned by later stages (interval80, p_dside_win, simulation seats) are omitted rather than faked until
`add_simulation` merges the Phase 5 simulation in. proj_margin = pres2024 + state_swing + turnout + early_vote (turnout and early vote are 0 for
states without a turnout_component / early_vote_component row); the exporter asserts that identity."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_VERSION = "0.5.0-phase5"
IDENTITY_TOL = 0.05


def _clean(x):
    if isinstance(x, float) and not np.isfinite(x):
        return None
    return round(x, 3) if isinstance(x, float) else x


def build_summary(national: dict, states: pd.DataFrame, races: pd.DataFrame, a: float, b: float,
                  run_id: str | None = None, early_vote: dict[str, float] | None = None,
                  turnout: dict[str, float] | None = None) -> dict:
    """races: races_2026.csv rows; states: swing.model output (contest == state_po in the live run).

    early_vote: {state_po: E_s} from output/early_vote_component.csv (Phase 4); missing states get 0.
    turnout: {state_po: T_s} from output/turnout_component.csv (Phase 5); missing states get 0."""
    by_state = states.set_index("state_po")
    out_races = []
    for r in races.itertuples():
        if r.state_po not in by_state.index:
            continue
        s = by_state.loc[r.state_po]
        components = {"national": national["s_nat"], "state_poll": s.s_poll, "market": None,
                      "market_weight": s.market_weight, "state_swing": s.swing,
                      "turnout": float((turnout or {}).get(r.state_po, 0.0)),
                      "early_vote": float((early_vote or {}).get(r.state_po, 0.0))}
        proj = s.m0 + components["state_swing"] + components["turnout"] + components["early_vote"]
        assert abs(proj - (s.proj_margin + components["turnout"] + components["early_vote"])) <= IDENTITY_TOL, (r.state_po, proj, s.proj_margin)
        out_races.append({
            "state": r.state_po, "class": int(r._2), "special": str(r.special).lower() == "true",
            "incumbent": r.incumbent, "incumbent_party": r.incumbent_party,
            "dside": {"name": r.dside_name or None, "party": r.dside_party,
                      "endorsed_by_dem": str(r.dside_endorsed_by_dem).lower() == "true"},
            "rside": {"name": r.rside_name or None, "party": r.rside_party},
            "rcv": str(r.rcv).lower() == "true",
            "pres2024_margin": _clean(float(s.m0)), "proj_margin": _clean(float(proj)),
            "shift": _clean(float(s.swing)), "swing_source": s.swing_source,
            "components": {k: _clean(float(v)) if v is not None else None for k, v in components.items()},
            "polls": {"n": int(s.n_polls), "avg_margin": _clean(float(s.poll_margin)), "n_eff": _clean(float(s.n_eff))},
        })
    return {
        "run_id": run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "as_of": national["as_of"], "model_version": MODEL_VERSION, "phase": 5,
        "national": {
            "generic_ballot": {"margin": _clean(national["gb_margin"]), "source": national["gb_source"],
                               "n_polls": national["gb_n_polls"], "n_eff": _clean(float(national["gb_n_eff"])),
                               "se": _clean(float(national["gb_se"]))},
            "npv2024": _clean(national["npv_baseline"]), "s_nat": _clean(national["s_nat"]),
        },
        "weights": {"national": a, "state_poll": b},
        "races": out_races,
    }


def add_simulation(summary: dict, sim: dict, tol: float = 0.05) -> dict:
    """Merge sim/outputs.summarize() into summary.json (plan §9.1): p_dside_win, interval80, seats, tipping points.

    The deterministic proj_margin stays the headline; the simulation mean must agree with it to within `tol`."""
    by = sim["states"]
    for r in summary["races"]:
        x = by.get(r["state"])
        if x is None:
            continue
        assert abs(x["m_hat"] - r["proj_margin"]) <= tol, (r["state"], x["m_hat"], r["proj_margin"])
        r["p_dside_win"] = x["p_dside_win"]
        r["interval80"] = [x["lo"], x["hi"]]
    summary["simulation"] = {"n_draws": sim["n_draws"], "interval": sim["interval"], "seats": sim["seats"],
                             "tipping": sim["tipping"]}
    return summary


def write_summary(summary: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    return path
