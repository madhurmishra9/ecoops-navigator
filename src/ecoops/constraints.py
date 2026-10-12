"""Constraint engine: resilience, security, data retention, accessibility, performance, change control."""

from __future__ import annotations

from typing import Any

import numpy as np

from .models import ConstraintCheck, Opportunity


def _py(value: Any) -> Any:
    return value.item() if isinstance(value, np.generic) else value


def _matches(when: dict[str, list], opp: Opportunity, asset: dict[str, Any]) -> bool:
    for key, allowed in when.items():
        value = opp.action_class if key == "action_class" else _py(asset.get(key))
        if value not in allowed:
            return False
    return True


def evaluate(opp: Opportunity, asset: dict[str, Any], rules: list[dict]) -> list[ConstraintCheck]:
    checks = []
    for rule in rules:
        if _matches(rule.get("when", {}), opp, asset):
            checks.append(ConstraintCheck(
                rule_id=rule["id"], category=rule["category"], effect=rule["effect"], reason=rule["reason"],
                alternative=rule.get("alternative", ""), prerequisite=rule.get("prerequisite", ""),
            ))
    return checks


def apply_constraints(opportunities: list[Opportunity], assets: dict[str, dict[str, Any]], config: dict) -> None:
    """Attach constraint checks and set each opportunity's status in place."""
    rules = config.get("rules", [])
    for opp in opportunities:
        checks = evaluate(opp, assets.get(opp.entity, {}), rules)
        opp.constraints = checks
        effects = {c.effect for c in checks}
        opp.constraint_status = "blocked" if "block" in effects else "conditional" if "conditional" in effects else "clear"
        for c in checks:
            if c.prerequisite and c.prerequisite not in opp.prerequisites:
                opp.prerequisites.append(c.prerequisite)
