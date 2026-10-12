"""Core data structures: evidence, constraint checks and opportunities."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PROVENANCE = ("observed", "derived", "assumed", "missing")
DOMAINS = ("digital", "physical")
EFFORTS = ("S", "M", "L")
STATUSES = ("clear", "conditional", "blocked")
NEXT_STEPS = ("automate", "investigate", "test", "pilot", "monitor", "escalate")
IMPACT_KEYS = ("energy_kwh", "co2e_kg", "cost")


@dataclass
class Evidence:
    """One fact supporting a flag, labelled with where it came from."""

    label: str
    value: Any
    unit: str = ""
    provenance: str = "observed"
    source: str = ""

    def __post_init__(self) -> None:
        if self.provenance not in PROVENANCE:
            raise ValueError(f"provenance must be one of {PROVENANCE}, got {self.provenance!r}")


@dataclass
class ConstraintCheck:
    rule_id: str
    category: str
    effect: str  # block | conditional
    reason: str
    alternative: str = ""
    prerequisite: str = ""


@dataclass
class Opportunity:
    """A candidate action on one asset, with evidence, impact, constraints and score."""

    detector: str
    action_class: str
    technology: str
    domain: str
    entity: str
    title: str
    root_cause: str
    proposed_action: str
    capacity_effect: str
    effort: str
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)
    baseline: dict[str, float] = field(default_factory=dict)  # analysis period
    savings: dict[str, float] = field(default_factory=dict)  # analysis period
    confidence_reasons: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    # --- enrichment (filled by the pipeline) ---
    owner_role: str = ""
    service: str = ""
    env: str = ""
    annual_baseline: dict[str, float] = field(default_factory=dict)
    annual_savings: dict[str, float] = field(default_factory=dict)
    constraint_status: str = "clear"
    constraints: list[ConstraintCheck] = field(default_factory=list)
    potential_score: float = 0.0
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    next_step: str = ""
    next_step_detail: str = ""
    review_step: str = ""
    narrative: str = ""

    def __post_init__(self) -> None:
        if self.domain not in DOMAINS:
            raise ValueError(f"domain must be one of {DOMAINS}")
        if self.effort not in EFFORTS:
            raise ValueError(f"effort must be one of {EFFORTS}")

    @property
    def id(self) -> str:
        return f"{self.action_class}:{self.entity}"

    @property
    def saving_pct(self) -> float:
        """Percentage reduction of the asset's dominant impact (CO2e, else cost)."""
        for key in ("co2e_kg", "cost"):
            base = self.baseline.get(key, 0.0)
            if base > 0 and self.savings.get(key, 0.0) > 0:
                return 100.0 * self.savings[key] / base
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = self.id
        data["saving_pct"] = round(self.saving_pct, 1)
        return data

    def to_row(self) -> dict[str, Any]:
        """Flat record for tables and CSV export."""
        return {
            "id": self.id,
            "score": self.score,
            "potential_score": self.potential_score,
            "title": self.title,
            "technology": self.technology,
            "domain": self.domain,
            "entity": self.entity,
            "root_cause": self.root_cause,
            "action_class": self.action_class,
            "constraint_status": self.constraint_status,
            "next_step": self.next_step,
            "effort": self.effort,
            "confidence": round(self.confidence, 2),
            "annual_energy_kwh": round(self.annual_savings.get("energy_kwh", 0.0), 1),
            "annual_co2e_kg": round(self.annual_savings.get("co2e_kg", 0.0), 1),
            "annual_cost": round(self.annual_savings.get("cost", 0.0), 2),
            "saving_pct": round(self.saving_pct, 1),
            "owner_role": self.owner_role,
            "service": self.service,
            "env": self.env,
            "capacity_effect": self.capacity_effect,
            "missing_information": "; ".join(self.missing_information),
            "constraints": "; ".join(f"{c.rule_id} ({c.effect})" for c in self.constraints),
        }
