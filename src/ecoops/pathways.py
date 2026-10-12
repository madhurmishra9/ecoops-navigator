"""Reduction pathways: Quick Wins, Digital Efficiency First, Balanced Operations.

All three are views over the same scored portfolio. Blocked actions are never included
(they go to the human-review queue) and each asset appears at most once per pathway.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .models import IMPACT_KEYS, Opportunity

WAVE_LABELS = {1: "Wave 1 - now (0-4 weeks)", 2: "Wave 2 - next (1-3 months)", 3: "Wave 3 - later (3-6 months)"}


@dataclass
class Pathway:
    key: str
    name: str
    description: str
    actions: list[dict] = field(default_factory=list)
    totals: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def wave(o: Opportunity) -> int:
    if o.effort == "L":
        return 3
    if o.effort == "S" and o.constraint_status == "clear":
        return 1
    return 2


def _one_per_entity(opps: list[Opportunity]) -> list[Opportunity]:
    best: dict[str, Opportunity] = {}
    for o in sorted(opps, key=lambda x: x.score, reverse=True):
        best.setdefault(o.entity, o)
    return list(best.values())


def _build(key: str, name: str, description: str, selected: list[Opportunity]) -> Pathway:
    selected = sorted(selected, key=lambda o: (wave(o), -o.score))
    actions = [
        dict(id=o.id, title=o.title, entity=o.entity, technology=o.technology, domain=o.domain, wave=wave(o),
             wave_label=WAVE_LABELS[wave(o)], next_step=o.next_step, score=o.score, effort=o.effort,
             confidence=o.confidence, owner_role=o.owner_role, constraint_status=o.constraint_status,
             **{f"annual_{k}": round(o.annual_savings.get(k, 0.0), 1) for k in IMPACT_KEYS})
        for o in selected
    ]
    totals = {f"annual_{k}": round(sum(o.annual_savings.get(k, 0.0) for o in selected), 1) for k in IMPACT_KEYS}
    co2 = totals["annual_co2e_kg"]
    digital_co2 = sum(o.annual_savings.get("co2e_kg", 0.0) for o in selected if o.domain == "digital")
    totals.update(
        actions=len(selected),
        digital_actions=sum(1 for o in selected if o.domain == "digital"),
        physical_actions=sum(1 for o in selected if o.domain == "physical"),
        digital_share_of_co2e=round(digital_co2 / co2, 3) if co2 > 0 else 0.0,
        mean_confidence=round(sum(o.confidence for o in selected) / len(selected), 2) if selected else 0.0,
        needs_approval_or_test=sum(1 for o in selected if o.constraint_status == "conditional"),
        effort_mix={e: sum(1 for o in selected if o.effort == e) for e in ("S", "M", "L")},
    )
    return Pathway(key=key, name=name, description=description, actions=actions, totals=totals)


def build_pathways(opportunities: list[Opportunity], cfg: dict) -> list[Pathway]:
    p = cfg["pathways"]
    actionable = _one_per_entity([o for o in opportunities if o.constraint_status != "blocked"])

    quick = [o for o in actionable if o.effort == "S" and o.constraint_status == "clear"
             and o.confidence >= p["quick_win_min_confidence"]]

    digital_first = [o for o in actionable if o.domain == "digital"] + \
                    [o for o in actionable if o.domain == "physical" and o.effort == "S"]

    n = min(p["balanced_max_actions"], len(actionable))
    n_dig = round(n * p["balanced_digital_share"])
    digital = sorted([o for o in actionable if o.domain == "digital"], key=lambda o: o.score, reverse=True)
    physical = sorted([o for o in actionable if o.domain == "physical"], key=lambda o: o.score, reverse=True)
    balanced = digital[:n_dig] + physical[: n - n_dig]
    if len(balanced) < n:  # top up from whichever domain still has candidates
        rest = [o for o in sorted(actionable, key=lambda o: o.score, reverse=True) if o not in balanced]
        balanced += rest[: n - len(balanced)]

    return [
        _build("quick_wins", "Quick Wins",
               "Low-effort, high-confidence actions with no open constraints. Fast, low-risk proof of value.", quick),
        _build("digital_first", "Digital Efficiency First",
               "Every actionable digital opportunity, plus physical quick wins. Maximises the digital-estate "
               "emphasis of the brief; includes items that need tests or approvals.", digital_first),
        _build("balanced", "Balanced Operations",
               f"Top {n} actions by score, mixed ~{p['balanced_digital_share']:.0%} digital / "
               f"{1 - p['balanced_digital_share']:.0%} physical by count.", balanced),
    ]
