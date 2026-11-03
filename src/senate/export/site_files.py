"""Site artifacts (plan §9): per-state files, counties_national, methodology params, backtest summary and a
site-shaped data_health, plus the site-facing fields of summary.json. Shapes mirror site/src/lib/data/types.ts;
site/scripts/make_mock_data.mjs is the reference. Everything here is real (`mock` is false).

Runs after `sim` (`make export`). Reads output/ and data/processed/; rewrites output/summary.json in place
(idempotent) and writes output/states/, counties_national.json, methodology_params.json, backtest_summary.json and
site_data_health.json (publish.py publishes the latter as data_health.json; stages.py keeps its own report)."""
from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import structlog

from ..config import ROOT, Settings, load_config
from ..ingest._base import processed_dir

OUTPUT = ROOT / "output"

log = structlog.get_logger()

GROUPS = ["wnh_college", "wnh_noncollege", "black", "hispanic", "asian", "other"]
Z80 = 1.2816
POLLS_RECENT = 6

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}

# Required keys per artifact, mirroring types.ts (optional fields are not listed).
RACE_KEYS = {"state", "class", "special", "incumbent", "incumbent_party", "dside", "rside", "rcv",
             "pres2024_margin", "proj_margin", "shift", "swing_source", "components", "polls"}
COMPONENT_KEYS = {"national", "state_poll", "market", "market_weight", "state_swing", "turnout", "early_vote"}
COUNTY_KEYS = {"geoid", "name", "pres2024_margin", "proj_margin", "shift", "interval80", "votes_2024", "votes_proj",
               "p_dside_win", "group_shares", "group_swings", "flags"}
STATE_FILE_KEYS = {"state", "run_id", "as_of", "counties", "groups", "early_vote", "polls_recent"}
POLL_KEYS = {"pollster", "end", "n", "pop", "margin"}
SENATE_KEYS = {"d_seats_median", "d_seats_p10", "d_seats_p90", "p_d_control", "distribution"}
METHODOLOGY_KEYS = {"weights", "half_life_days", "market", "earlyvote", "county", "sim"}


def _f(x, nd: int = 1):
    """JSON-safe rounded float (NaN/inf -> None)."""
    if x is None:
        return None
    x = float(x)
    return round(x, nd) if math.isfinite(x) else None


def _phi(x: np.ndarray) -> np.ndarray:
    from scipy.special import erf
    return 0.5 * (1.0 + erf(x / math.sqrt(2.0)))


# --------------------------------------------------------------------------- summary
def augment_summary(summary: dict, sim: dict, ev_detail: dict[str, str], ei_status: dict[str, str],
                    county_method: dict[str, str]) -> dict:
    """Site-facing fields on summary.json: race names/ev_detail/ei_status/county_method and national.senate."""
    for r in summary["races"]:
        s = r["state"]
        r["name"] = STATE_NAMES.get(s, s)
        r["ev_detail"] = ev_detail.get(s, "none")
        if s in ei_status:
            r["ei_status"] = ei_status[s]
        if s in county_method:
            r["county_method"] = county_method[s]
    seats = sim["seats"]
    pmf = {str(k): float(v) for k, v in seats["pmf"].items() if float(v) > 5e-4}
    lo, hi = seats["interval80"]
    summary["national"]["senate"] = {
        "d_seats_median": float(seats["median"]), "d_seats_p10": float(lo), "d_seats_p90": float(hi),
        "p_d_control": round(float(seats["p_control"]), 3), "threshold": float(seats["threshold"]),
        "distribution": {k: round(v, 3) for k, v in pmf.items()},
    }
    summary["mock"] = False
    return summary


# --------------------------------------------------------------------------- state files
def _county_interval(cty: pd.DataFrame, state_sim: dict | None) -> pd.DataFrame:
    """County lo/hi/p: from sim_counties where available, else the state's own band shifted to the county margin
    (states excluded from the county layer by the roll-up check). Returns a column `interval_src`."""
    c = cty.copy()
    have = c.lo.notna() & c.hi.notna()
    c["interval_src"] = np.where(have, "county_sim", "state_band")
    if (~have).any():
        if state_sim is None:
            raise ValueError("no county interval and no state simulation band")
        half_lo = float(state_sim["m_hat"]) - float(state_sim["lo"])
        half_hi = float(state_sim["hi"]) - float(state_sim["m_hat"])
        c.loc[~have, "lo"] = c.m_hat - half_lo
        c.loc[~have, "hi"] = c.m_hat + half_hi
        sd = max((half_lo + half_hi) / 2 / Z80, 1e-6)
        c.loc[~have, "p_dside_win"] = _phi((c.m_hat[~have] / sd).to_numpy())
    return c


def build_state_file(state: str, counties: pd.DataFrame, state_sim: dict | None, run_id: str, as_of: str,
                     group_shares: pd.DataFrame, polls: pd.DataFrame, early_vote: dict | None,
                     ei_fallback: bool) -> dict:
    """counties: geoid, name, m0, m_hat, omega, votes_2024, lo, hi, p_dside_win, county_method."""
    c = _county_interval(counties, state_sim)
    shares = group_shares.reindex(c.geoid) if len(group_shares) else None
    rows = []
    for i, x in enumerate(c.itertuples()):
        flags = []
        if x.interval_src == "state_band":
            flags.append("interval_from_state_band")
        if ei_fallback:
            flags.append("ei_fallback")
        gs = {}
        if shares is not None:
            gs = {g: _f(shares.iloc[i][g], 3) for g in GROUPS if g in shares.columns and pd.notna(shares.iloc[i][g])}
        rows.append({
            "geoid": x.geoid, "name": x.name, "pres2024_margin": _f(x.m0), "proj_margin": _f(x.m_hat),
            "shift": _f(x.m_hat - x.m0), "interval80": [_f(x.lo), _f(x.hi)],
            "votes_2024": int(x.votes_2024) if pd.notna(x.votes_2024) else 0,
            "votes_proj": int(round(x.omega)) if pd.notna(x.omega) else 0,
            "p_dside_win": _f(x.p_dside_win, 3), "group_shares": gs, "group_swings": {},
            "method": x.county_method, "flags": flags,
        })
    return {"state": state, "run_id": run_id, "as_of": as_of, "mock": False, "counties": rows,
            "groups": [], "early_vote": early_vote, "polls_recent": polls_recent(polls)}


def polls_recent(audit: pd.DataFrame | None, k: int = POLLS_RECENT) -> list[dict]:
    """Most recent polls the state average used (output/poll_audit/<ST>.csv)."""
    if audit is None or not len(audit):
        return []
    a = audit.copy()
    a["end"] = pd.to_datetime(a.field_end).dt.strftime("%Y-%m-%d")
    a = a.sort_values("end", ascending=False).head(k)
    return [{"pollster": str(r.pollster), "end": r.end, "n": int(r.n) if pd.notna(r.n) else 0,
             "pop": str(r.pop), "margin": _f(r.margin)} for r in a.itertuples()]


def early_vote_block(row: pd.Series | None, detail: str) -> dict | None:
    if row is None or detail == "none":
        return None
    out: dict = {"as_of_days_out": int(row["as_of_days_out"]) if pd.notna(row.get("as_of_days_out")) else 0,
                 "cap_binding": bool(row.get("cap_binding", False))}
    for cyc in ("2022", "2018", "2024"):
        v = row.get(f"total_ratio_{cyc}")
        if v is not None and pd.notna(v):
            out[f"vs_{cyc}"] = {"total_ratio": _f(v, 3)}
    return out


# --------------------------------------------------------------------------- other artifacts
def methodology_params(cfg: Settings) -> dict:
    return {
        "weights": {"national": cfg.swing.weights.national, "state_poll": cfg.swing.weights.state_poll},
        "half_life_days": {"senate": cfg.polls.half_life_days.senate, "generic": cfg.polls.half_life_days.generic},
        "market": {"enabled": bool(cfg.swing.market.enabled), "mu": cfg.swing.market.mu,
                   "weight_cap": cfg.swing.market.weight_cap},
        "earlyvote": {"cap_pts": cfg.earlyvote.cap_pts, "shrink": cfg.earlyvote.shrink},
        "county": {"max_tilt": cfg.county.max_tilt},
        "sim": {"n_draws": cfg.sim.n_draws, "control_threshold": cfg.sim.control_threshold},
    }


def site_data_health(health: dict, run_id: str, as_of: str, extra_flags: list[str]) -> dict:
    """Site shape {sources:[{name,status,retrieved_at}], flags} from the pipeline's {stages, tables, ...} report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sources = []
    for name, st in (health.get("stages") or {}).items():
        if st.get("ok"):
            sources.append({"name": name, "status": "ok", "retrieved_at": now})
        else:
            sources.append({"name": name, "status": "fallback" if st.get("fallback") else "stale", "retrieved_at": now})
    return {"sources": sources, "flags": extra_flags, "run_id": run_id, "as_of": as_of}


# --------------------------------------------------------------------------- validation
def validate_site_files(out: Path) -> None:
    """Check the written artifacts against the keys the site requires (types.ts). Raises AssertionError."""
    out = Path(out)
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s.get("mock") is False, "summary.json must have mock:false"
    assert {"run_id", "as_of", "model_version", "national", "weights", "races"} <= set(s)
    assert SENATE_KEYS <= set(s["national"].get("senate", {})), "national.senate incomplete"
    for r in s["races"]:
        missing = RACE_KEYS - set(r)
        assert not missing, (r.get("state"), "race missing", missing)
        assert COMPONENT_KEYS <= set(r["components"]), (r["state"], "components")
        assert {"n", "avg_margin", "n_eff"} <= set(r["polls"]), (r["state"], "polls")
        assert r.get("interval80") and len(r["interval80"]) == 2 and 0 <= r["p_dside_win"] <= 1, r["state"]
        # shift is the model's state swing; county shifts average to it (turnout/early vote enter via the weights)
        assert abs(r["shift"] - r["components"]["state_swing"]) < 0.01, (r["state"], "shift")
    states = {r["state"] for r in s["races"]}
    for f in (out / "states").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert STATE_FILE_KEYS <= set(d), (f.name, STATE_FILE_KEYS - set(d))
        assert f.stem in states
        for c in d["counties"]:
            assert COUNTY_KEYS <= set(c), (f.name, c.get("geoid"), COUNTY_KEYS - set(c))
            assert len(c["interval80"]) == 2 and None not in c["interval80"] and c["p_dside_win"] is not None
        for p in d["polls_recent"]:
            assert POLL_KEYS <= set(p)
    cn = json.loads((out / "counties_national.json").read_text(encoding="utf-8"))
    assert cn["cols"] == ["geoid", "pres2024", "proj", "shift", "p"] and all(len(r) == 5 for r in cn["rows"])
    assert METHODOLOGY_KEYS <= set(json.loads((out / "methodology_params.json").read_text(encoding="utf-8")))
    h = json.loads((out / "site_data_health.json").read_text(encoding="utf-8"))
    assert {"sources", "flags"} <= set(h) and all({"name", "status", "retrieved_at"} <= set(x) for x in h["sources"])
    assert all(x["status"] in ("ok", "fallback", "stale") for x in h["sources"])


# --------------------------------------------------------------------------- orchestration
def _mode(s: pd.Series) -> str:
    return str(s.mode().iloc[0]) if len(s) else "none"


def export_site(cfg: Settings | None = None, out: Path = OUTPUT) -> dict:
    cfg = cfg or load_config()
    out, proc = Path(out), processed_dir()
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    sim = json.loads((out / "sim_summary.json").read_text(encoding="utf-8"))
    if "p_dside_win" not in summary["races"][0]:
        raise RuntimeError("summary.json has no simulation fields: run `sim` first")
    run_id, as_of = summary["run_id"], summary["as_of"]

    cs = pd.read_parquet(proc / "county_swing_2026.parquet")
    sc = pd.read_csv(out / "sim_counties.csv", dtype={"geoid": str}).drop(columns=["m_hat"], errors="ignore")
    geo = pd.read_parquet(proc / "geographies.parquet").set_index("geoid")
    pres = pd.read_parquet(proc / "pres_county.parquet")
    pres = pres[pres.year == 2024].drop_duplicates("geoid").set_index("geoid")
    ei = pd.read_parquet(proc / "ei_group_vote.parquet")
    ei["state_po"] = ei.geoid.map(geo.state_po)
    ei_status = {s: ("fallback" if (g.ei_status == "fallback").mean() > 0.5 else "ok") for s, g in ei.groupby("state_po")}
    n_g = ei.pivot_table(index="geoid", columns="group", values="n_group", aggfunc="first")
    shares = n_g.div(n_g.sum(axis=1).where(n_g.sum(axis=1) > 0), axis=0)

    ev_summ_p = out / "early_vote_summary.json"
    evs = json.loads(ev_summ_p.read_text(encoding="utf-8")) if ev_summ_p.exists() else {}
    not_full = {x["state_po"]: x["ev_detail"] for x in evs.get("not_full", [])}
    states_in_run = [r["state"] for r in summary["races"]]
    ev_detail = {s: not_full.get(s, "full" if evs else "none") for s in states_in_run}
    evc_p = out / "early_vote_component.csv"
    evc = pd.read_csv(evc_p).set_index("state_po") if evc_p.exists() else pd.DataFrame()
    county_method = cs.groupby("state_po").county_method.agg(_mode).to_dict()
    for st in states_in_run:
        county_method.setdefault(st, "none")  # e.g. Alaska: no district->borough crosswalk, so no county layer

    augment_summary(summary, sim, ev_detail, ei_status, county_method)

    cty = cs.merge(sc, on="geoid", how="left").assign(name=lambda d: d.geoid.map(geo.name),
                                                       votes_2024=lambda d: d.geoid.map(pres.votes_total))
    if cty.name.isna().any():
        raise RuntimeError(f"{int(cty.name.isna().sum())} counties without a name in geographies")
    (out / "states").mkdir(exist_ok=True)
    nat_rows: list[list] = []
    flags: list[str] = []
    for st in states_in_run:
        g = cty[cty.state_po == st]
        if g.empty:  # still write the file (empty counties) so the site's prerender finds it
            flags.append(f"{st}: no county-level data")
        audit_p = out / "poll_audit" / f"{st}.csv"
        audit = pd.read_csv(audit_p) if audit_p.exists() else None
        evrow = evc.loc[st] if st in evc.index else None
        doc = build_state_file(st, g, sim["states"].get(st), run_id, as_of, shares, audit,
                               early_vote_block(evrow, ev_detail[st]), ei_status.get(st) == "fallback")
        (out / "states" / f"{st}.json").write_text(json.dumps(doc, allow_nan=False), encoding="utf-8")
        nat_rows += [[c["geoid"], c["pres2024_margin"], c["proj_margin"], c["shift"], c["p_dside_win"]] for c in doc["counties"]]
    (out / "counties_national.json").write_text(
        json.dumps({"cols": ["geoid", "pres2024", "proj", "shift", "p"], "rows": nat_rows}, allow_nan=False), encoding="utf-8")
    (out / "methodology_params.json").write_text(json.dumps(methodology_params(cfg)), encoding="utf-8")
    bt = out / "backtest" / "metrics.json"
    if bt.exists():
        shutil.copy2(bt, out / "backtest_summary.json")

    # data-health flags: what the reader should know about the inputs of this run
    n_ei = sum(v == "fallback" for v in ei_status.values())
    if n_ei:
        flags.append(f"County group estimates fell back to uniform swing in {n_ei} of {len(ei_status)} states (EI did not converge).")
    if summary["national"]["generic_ballot"].get("n_polls", 0) and "fallback" in str(summary["national"]["generic_ballot"].get("source")):
        flags.append("Generic ballot uses the aggregator-headline median, not raw polls.")
    if sim.get("rollup_excluded"):
        flags.append("County intervals use the state band in: " + ", ".join(sim["rollup_excluded"]) + ".")
    if all(v == "none" for v in ev_detail.values()):
        flags.append("No early-vote data this run.")
    flags.append("No crosstab polls this run: group swings are not shown.")
    health_p = out / "data_health.json"
    health = json.loads(health_p.read_text(encoding="utf-8")) if health_p.exists() else {}
    (out / "site_data_health.json").write_text(json.dumps(site_data_health(health, run_id, as_of, flags)), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    validate_site_files(out)
    log.info("site_files_written", states=len(states_in_run), counties=len(nat_rows))
    return {"states": len(states_in_run), "counties": len(nat_rows), "flags": flags}
