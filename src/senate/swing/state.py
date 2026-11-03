"""State poll swing and the 'polled' rule (plan §6.4)."""
from __future__ import annotations

from ..config import SwingState
from ..polls.average import PollAverage


def state_poll_swing(poll_margin: float, m0: float) -> float:
    """S_poll = Senate poll average minus the state's baseline presidential margin."""
    return poll_margin - m0


def is_polled(avg: PollAverage, cfg: SwingState) -> bool:
    """Polled iff >= min_polls recent polls and n_eff >= min_n_eff (polls already limited to max_age_days)."""
    return avg.available and avg.n_polls >= cfg.min_polls and avg.n_eff >= cfg.min_n_eff
