"""National swing (plan §6.3)."""
from __future__ import annotations


def national_swing(gb_avg_margin_2p: float, npv2024_margin_2p: float) -> float:
    """S_nat = generic-ballot margin minus the baseline national presidential margin."""
    return gb_avg_margin_2p - npv2024_margin_2p
