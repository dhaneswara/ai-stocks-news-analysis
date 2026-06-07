from __future__ import annotations

from typing import Literal

GRADE_STRONG_MIN = 60.0
GRADE_WEAK_MAX = 40.0


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def is_hit(recommendation: str, return_pct: float, hold_band_pct: float) -> bool:
    """buy is right if price rose, sell if it fell, hold if it stayed within the band."""
    if recommendation == "buy":
        return return_pct > 0
    if recommendation == "sell":
        return return_pct < 0
    return abs(return_pct) <= hold_band_pct


def score_call(recommendation: str, return_pct: float, hold_band_pct: float,
               score_scale_pct: float) -> float:
    """0..100, magnitude-aware. 50 = neutral / at the hit boundary."""
    if recommendation == "hold":
        band = hold_band_pct if hold_band_pct > 0 else 1e-9
        closeness = (band - abs(return_pct)) / band
        return _clamp(50.0 + 50.0 * closeness)
    scale = score_scale_pct if score_scale_pct > 0 else 1e-9
    direction = 1.0 if recommendation == "buy" else -1.0
    aligned = direction * return_pct
    return _clamp(50.0 + 50.0 * (aligned / scale))


def grade_for(avg_score: float) -> Literal["Strong", "Mixed", "Weak"]:
    if avg_score >= GRADE_STRONG_MIN:
        return "Strong"
    if avg_score <= GRADE_WEAK_MAX:
        return "Weak"
    return "Mixed"


def is_overconfident(hit_confs: list[float], miss_confs: list[float]) -> bool:
    """True when, on average, missed calls were at least as confident as correct ones."""
    if not hit_confs or not miss_confs:
        return False
    return (sum(miss_confs) / len(miss_confs)) >= (sum(hit_confs) / len(hit_confs))
