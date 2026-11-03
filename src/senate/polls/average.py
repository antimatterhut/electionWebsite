"""Poll averaging for the generic ballot and each Senate race (plan §6.2)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from ..config import Polls, Settings
from ..ingest import _polls as P
from . import house_effects as HE
from . import lv_rv
from .weights import cap_pollster_weights, margin_2p, poll_weights

POP_RANK = {"LV": 0, "RV": 1, "A": 2}
MATCHUP_RANK = {"rcv_final": 0, "two_way": 1, "multi": 2}


@dataclass
class PollAverage:
    margin: float
    se: float
    n_eff: float
    n_polls: int
    weights_df: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)

    @property
    def available(self) -> bool:
        return self.n_polls > 0 and np.isfinite(self.margin)


def empty_average() -> PollAverage:
    return PollAverage(float("nan"), float("nan"), 0.0, 0, pd.DataFrame())


# ---------------------------------------------------------------- tidy inputs
def tidy_generic(polls: pd.DataFrame) -> pd.DataFrame:
    d = polls.copy()
    d["contest"] = "GB"
    d["margin"] = margin_2p(d.d_pct, d.r_pct)
    d["matchup_type"] = "two_way"
    return _finish_tidy(d)


def tidy_senate(polls: pd.DataFrame, rcv_states: set[str], transfer_to_dside: float) -> pd.DataFrame:
    """Convert to two-party margins. RCV states (plan §2.2): explicit final-round head-to-head first, else first-round
    shares with minor-candidate transfers (`transfer_to_dside` to the D-side, the rest to R), else two-party."""
    d = polls.copy()
    d["contest"] = d.state_po
    dp, rp = d.dside_pct.astype(float), d.rside_pct.astype(float)
    other = d.other_pct.fillna(0.0).astype(float)
    rcv_multi = d.state_po.isin(rcv_states) & d.matchup_type.eq("multi")
    dp = np.where(rcv_multi, dp + transfer_to_dside * other, dp)
    rp = np.where(rcv_multi, rp + (1 - transfer_to_dside) * other, rp)
    d["margin"] = margin_2p(dp, rp)
    return _finish_tidy(d)


def _finish_tidy(d: pd.DataFrame) -> pd.DataFrame:
    d["field_end"] = pd.to_datetime(d.field_end)
    d["partisan"] = d.partisan.fillna(False).astype(bool)
    if "tracking" not in d:
        d["tracking"] = False
    d["tracking"] = d.tracking.fillna(False).astype(bool)
    if "n" not in d:
        d["n"] = np.nan
    return d[d.margin.notna()].reset_index(drop=True)


# ---------------------------------------------------------------- selection
def select_recent(polls: pd.DataFrame, as_of: date, max_age_days: float) -> pd.DataFrame:
    """Polls fielded (field_end) on or before as_of and no older than max_age_days."""
    age = (pd.Timestamp(as_of) - pd.to_datetime(polls.field_end)).dt.days
    return polls[(age >= 0) & (age <= max_age_days)].reset_index(drop=True)


def drop_trackers(polls: pd.DataFrame, gap_days: int) -> pd.DataFrame:
    """Overlapping releases of a tracking poll: keep one per pollster per `gap_days`."""
    tr = polls.tracking
    if not tr.any():
        return polls
    kept = P.drop_overlapping_trackers(polls[tr], gap_days, ["contest"])
    return pd.concat([polls[~tr], kept]).reset_index(drop=True)


def one_per_period(polls: pd.DataFrame) -> pd.DataFrame:
    """One row per (contest, pollster, field_end): prefer final-round/two-way matchups, then LV > RV > A."""
    d = polls.assign(_m=polls.matchup_type.map(MATCHUP_RANK).fillna(3), _p=polls["pop"].map(POP_RANK).fillna(3))
    d = d.sort_values(["_m", "_p"], kind="stable").drop_duplicates(["contest", "pollster", "field_end"])
    return d.drop(columns=["_m", "_p"]).sort_index().reset_index(drop=True)


# ---------------------------------------------------------------- average
def poll_average(polls: pd.DataFrame, as_of: date, cfg: Polls, house_effects: dict[str, float] | None = None,
                 kind: str = "senate", ratings: dict[str, float] | None = None) -> PollAverage:
    """Average ONE contest's tidy polls (`margin`, plus `delta` from the LV/RV step if present).

    Weights are computed here unless the frame already carries a `w` column (the pooled pipeline path)."""
    if polls.empty:
        return empty_average()
    d = polls.copy()
    if "w" not in d:
        d = poll_weights(d, as_of, kind, cfg, ratings)
    d = d[d.w > 0].reset_index(drop=True)
    if d.empty:
        return empty_average()
    he = house_effects or {}
    delta = d["delta"] if "delta" in d else 0.0
    d["h"] = d.pollster.map(lambda p: he.get(p, 0.0))
    d["m_adj"] = d.margin + delta - d.h
    w_hat, _ = cap_pollster_weights(d.w.to_numpy(), d.pollster.to_numpy(), cfg.pollster_cap, cfg.pollster_cap_few)
    d["w_hat"] = w_hat
    m_hat = float((w_hat * d.m_adj).sum())
    n_eff = float(1.0 / (w_hat**2).sum())
    se = float(np.sqrt(cfg.sigma_poll**2 / n_eff + cfg.sigma_floor**2))
    return PollAverage(m_hat, se, n_eff, len(d), d)


@dataclass
class PollingResult:
    generic: PollAverage
    states: dict[str, PollAverage]
    house_effects: dict[str, float]
    delta_lv: float
    n_lv_rv_pairs: int


def run_poll_averages(generic: pd.DataFrame, senate: pd.DataFrame, as_of: date, cfg: Settings,
                      ratings: dict[str, float] | None, rcv_states: set[str] | None = None,
                      states: list[str] | None = None) -> PollingResult:
    """The whole poll stage for one as-of date: tidy -> recent -> LV/RV delta -> one poll per period -> weights ->
    pooled house effects -> per-contest averages. Only polls with field_end <= as_of are used."""
    pc = cfg.polls
    rcv_states = rcv_states or set()
    g = tidy_generic(generic) if len(generic) else generic.assign(contest=[], margin=[])
    s = tidy_senate(senate, rcv_states, cfg.rcv.transfer_to_dside) if len(senate) else senate.assign(contest=[], margin=[])
    g = select_recent(g, as_of, pc.max_age_days.generic) if len(g) else g
    s = select_recent(s, as_of, pc.max_age_days.senate) if len(s) else s
    g = drop_trackers(g, pc.tracker_gap_days) if len(g) else g
    s = drop_trackers(s, pc.tracker_gap_days) if len(s) else s
    allp = pd.concat([g.assign(kind="generic"), s.assign(kind="senate")], ignore_index=True)
    delta, n_pairs = (pc.lv_rv.prior_delta, 0)
    if len(allp) and pc.lv_rv.adjust:
        delta, n_pairs = lv_rv.estimate_delta_lv(allp, pc.lv_rv)
    if len(allp):
        allp = one_per_period(allp)
        allp = lv_rv.adjust_population(allp, delta if pc.lv_rv.adjust else 0.0)
        allp["margin_adj"] = allp.margin + allp.delta
        parts = [poll_weights(allp[allp.kind == k], as_of, k, pc, ratings) for k in ("generic", "senate")
                 if (allp.kind == k).any()]
        allp = pd.concat(parts, ignore_index=True)
    he: dict[str, float] = {}
    if len(allp) and pc.house_effect.enabled:
        he = HE.estimate_house_effects(allp.assign(margin=allp.margin_adj), pc.house_effect)
    gb = poll_average(allp[allp.kind == "generic"], as_of, pc, he, "generic", ratings) if len(allp) else empty_average()
    out: dict[str, PollAverage] = {}
    for st in (states if states is not None else (sorted(allp[allp.kind == "senate"].contest.unique()) if len(allp) else [])):
        sub = allp[(allp.kind == "senate") & (allp.contest == st)] if len(allp) else allp
        out[st] = poll_average(sub, as_of, pc, he, "senate", ratings) if len(sub) else empty_average()
    return PollingResult(gb, out, he, float(delta), n_pairs)
