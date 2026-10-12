"""Recommendation engine: the next step for each opportunity, and its review step.

Next steps are recommendations for humans: automate | investigate | test | pilot | monitor | escalate.
"automate" means "codify as a guarded policy after owner approval" — the tool itself changes nothing.
"""

from __future__ import annotations

from .models import Opportunity


def assign_next_steps(opportunities: list[Opportunity], cfg: dict) -> None:
    ns = cfg["next_step"]
    for o in opportunities:
        cats = sorted({c.category for c in o.constraints})
        blocking = [c for c in o.constraints if c.effect == "block"]
        if o.constraint_status == "blocked":
            o.next_step = "escalate"
            alt = "; ".join(c.alternative for c in blocking if c.alternative)
            o.next_step_detail = (
                f"Blocked by {', '.join(c.category for c in blocking)} ({', '.join(c.rule_id for c in blocking)}): "
                f"{' '.join(c.reason for c in blocking)} Human decision required."
                + (f" Consider instead: {alt}" if alt else "")
            )
        elif "performance" in cats:
            o.next_step = "test"
            o.next_step_detail = "Run an NFT / performance test of the proposed configuration against the SLA before any change."
        elif o.confidence >= ns["automate_min_confidence"] and o.effort == "S" and o.constraint_status == "clear":
            o.next_step = "automate"
            o.next_step_detail = ("Codify as a guarded policy (lifecycle rule, schedule, pipeline condition) after owner "
                                  "approval, with monitoring and an easy override.")
        elif o.confidence >= ns["pilot_min_confidence"]:
            o.next_step = "pilot"
            o.next_step_detail = "Pilot on a limited scope, then compare realised against estimated outcome."
            if o.constraint_status == "conditional":
                o.next_step_detail = "Subject to " + ", ".join(o.prerequisites).lower() + ". " + o.next_step_detail
        elif o.confidence >= ns["investigate_min_confidence"]:
            o.next_step = "investigate"
            o.next_step_detail = "Close the information gaps first: " + "; ".join(o.missing_information) + "."
        else:
            o.next_step = "monitor"
            o.next_step_detail = "Evidence is weak; keep monitoring and revisit when more telemetry is available."
        owner = o.owner_role or "Asset owner"
        o.review_step = (f"{owner} to review within {ns['review_days']} days; after any change, re-run post-change "
                         "verification against this estimate.")
