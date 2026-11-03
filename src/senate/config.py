"""Pydantic loader for config/config.yaml (every key required, per plan §12)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Baseline(_M):
    year: int
    office: str


class Market(_M):
    enabled: bool
    mu: float
    weight_cap: float
    scale_by_volume: bool
    v_ref_usd: float
    sigma_pts: float
    prob_clip: list[float]
    max_abs_margin: float
    max_spread: float
    min_volume_usd: float
    max_age_hours: float
    platforms: list[str]


class SwingWeights(_M):
    national: float
    state_poll: float


class SwingNational(_M):
    generic_ballot_source: str


class SwingState(_M):
    min_polls: int
    min_n_eff: float


class Swing(_M):
    weights: SwingWeights
    market: Market
    scale_by_poll_volume: bool
    n_ref: float
    national: SwingNational
    state: SwingState


class HalfLife(_M):
    senate: float
    generic: float


class MaxAge(_M):
    senate: float
    generic: float


class PopWeight(_M):
    LV: float
    RV: float
    A: float


class HouseEffect(_M):
    enabled: bool
    shrink_k: float
    max_abs: float
    min_polls: int


class LvRv(_M):
    adjust: bool
    prior_delta: float
    min_pairs: int


class Polls(_M):
    half_life_days: HalfLife
    max_age_days: MaxAge
    n_cap: int
    n_min: int
    n_ref: int
    n_weight_max: float
    unrated_rating: float
    population_weight: PopWeight
    partisan_weight: float
    multiway_weight: float
    pollster_cap: float
    pollster_cap_few: float
    tracker_gap_days: int
    sigma_poll: float
    sigma_floor: float
    house_effect: HouseEffect
    lv_rv: LvRv


class Rcv(_M):
    transfer_to_dside: float


class Sampler(_M):
    chains: int
    tune: int
    draws: int
    target_accept: float


class EiSampler(Sampler):
    seed: int


class Crosstab(_M):
    min_n: int
    deff: float
    sampler: Sampler


class Ei(_M):
    groups: list[str]
    sampler: EiSampler
    rhat_max: float
    ess_min: float
    retry_target_accept: float
    min_counties_for_state_run: int
    pattern_persistence: float
    workers: int
    relative_turnout: dict[str, float]


class EarlyVote(_M):
    cap_pts: float
    cycle_weights: dict[int, float]
    party_cycles: list[int]
    party_cycle_weights: dict[int, float]
    shrink: float
    county_blend_kappa: float


class Turnout(_M):
    dropoff: dict[str, float]
    environment_beta: float
    rho_weights: dict[str, float]


class SimSd(_M):
    national: float
    region: float
    group: float
    state: float
    state_unpolled_extra: float
    county: float


class SimRho(_M):
    region_neighbor: float
    state_similarity: float


class Sim(_M):
    n_draws: int
    seed: int
    t_df: float
    sd: SimSd
    rho: SimRho
    control_threshold: float
    interval: list[float]


class Geo(_M):
    town_layer: bool


class Http(_M):
    min_interval_s: float
    retries: int
    user_agent: str


class Validation(_M):
    ei_flag_pts: float
    ei_fail_pts: float


class Diff(_M):
    alert_margin_pts: float
    alert_prob: float


class Results(_M):
    mode: str


class Backtest(_M):
    as_of_days_before: int


class Settings(_M):
    cycle: int
    as_of: date | None
    baseline: Baseline
    swing: Swing
    polls: Polls
    rcv: Rcv
    crosstab: Crosstab
    ei: Ei
    earlyvote: EarlyVote
    turnout: Turnout
    sim: Sim
    geo: Geo
    http: Http
    validation: Validation
    diff: Diff
    results: Results
    backtest: Backtest

    def resolved_as_of(self) -> date:
        return self.as_of or date.today()


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "config.yaml"


def load_config(path: str | Path | None = None) -> Settings:
    p = Path(path) if path else DEFAULT_CONFIG
    with open(p, encoding="utf-8") as f:
        return Settings.model_validate(yaml.safe_load(f))
