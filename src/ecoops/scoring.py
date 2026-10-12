"""EcoOps Opportunity Score (0-100): transparent, decomposable, about actions — never people."""

from __future__ import annotations

import math

from .models import Opportunity


def _lognorm(value: float, maximum: float) -> float:
    if maximum <= 0 or value <= 0:
        return 0.0
    return math.log1p(value) / math.log1p(maximum)


def score_all(opportunities: list[Opportunity], cfg: dict) -> None:
    """Score in place. Normalisation is relative to the largest saving in the current portfolio."""
    mix = cfg["impact_mix"]
    weights = cfg["weights"]
    total_w = sum(weights.values()) or 1.0
    w = {k: v / total_w for k, v in weights.items()}
    maxima = {k: max((o.annual_savings.get(k, 0.0) for o in opportunities), default=0.0) for k in mix}

    for o in opportunities:
        parts = {k: mix[k] * _lognorm(o.annual_savings.get(k, 0.0), maxima[k]) for k in mix}
        impact = sum(parts.values()) / (sum(mix.values()) or 1.0)
        ease = cfg["ease"][o.effort]
        impact_pts = 100 * w["impact"] * impact
        conf_pts = 100 * w["confidence"] * o.confidence
        ease_pts = 100 * w["ease"] * ease
        raw = impact_pts + conf_pts + ease_pts
        multiplier = cfg["status_multiplier"][o.constraint_status]
        o.potential_score = round(raw, 1)
        o.score = round(raw * multiplier, 1)
        o.score_breakdown = {
            "impact_points": round(impact_pts, 1),
            "confidence_points": round(conf_pts, 1),
            "ease_points": round(ease_pts, 1),
            "raw_score": round(raw, 1),
            "constraint_multiplier": multiplier,
            "final_score": o.score,
            **{f"impact_{k}_component": round(v, 3) for k, v in parts.items()},
        }
