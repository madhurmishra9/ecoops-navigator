"""End-to-end analysis: ingest -> normalise -> detect -> constrain -> score -> recommend -> pathways -> summary."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .constraints import apply_constraints
from .detectors import DetectorContext, run_detectors
from .impact import ImpactModel, scale
from .ingest import coerce_types, infer_period, validate
from .models import IMPACT_KEYS, Opportunity
from .narrative import explain
from .normalise import normalise
from .pathways import Pathway, build_pathways
from .recommend import assign_next_steps
from .scoring import score_all
from .settings import Settings, load_settings

MVP_BOUNDARY = ("Decision-quality prioritisation only: not production-grade carbon accounting, and no automated "
                "cloud, data, CI/CD, facilities or infrastructure remediation.")


@dataclass
class AnalysisResult:
    measures: pd.DataFrame
    footprint: pd.DataFrame
    opportunities: list[Opportunity]
    pathways: list[Pathway]
    summary: dict
    data_issues: list[str]
    period_start: pd.Timestamp
    period_end: pd.Timestamp
    period_days: int
    currency: str
    assumption_register: dict[str, str] = field(default_factory=dict)

    def get(self, opp_id: str) -> Opportunity | None:
        return next((o for o in self.opportunities if o.id == opp_id), None)

    def opportunity_frame(self) -> pd.DataFrame:
        rows = [o.to_row() for o in self.opportunities]
        df = pd.DataFrame(rows)
        return df.sort_values("score", ascending=False).reset_index(drop=True) if not df.empty else df


def _asset_lookup(data: dict[str, pd.DataFrame]) -> dict[str, dict]:
    assets = data.get("assets")
    if assets is None or assets.empty:
        return {}
    return {row["entity"]: row for row in assets.to_dict("records")}


def _summary(footprint: pd.DataFrame, opps: list[Opportunity], pathways: list[Pathway]) -> dict:
    annual = [f"annual_{k}" for k in IMPACT_KEYS]
    current = {k: round(float(footprint[k].sum()), 1) for k in annual}
    by_domain = footprint.groupby("domain")[annual].sum().round(1).reset_index().to_dict("records")
    by_tech = (footprint.groupby(["domain", "technology"])[annual].sum().round(1).reset_index()
               .sort_values("annual_co2e_kg", ascending=False).to_dict("records"))

    actionable = [o for o in opps if o.constraint_status != "blocked"]
    best: dict[str, Opportunity] = {}
    for o in sorted(actionable, key=lambda x: x.score, reverse=True):
        best.setdefault(o.entity, o)
    deduped = list(best.values())
    identified = {f"annual_{k}": round(sum(o.annual_savings.get(k, 0.0) for o in deduped), 1) for k in IMPACT_KEYS}
    split = {}
    for dom in ("digital", "physical"):
        sel = [o for o in deduped if o.domain == dom]
        split[dom] = {f"annual_{k}": round(sum(o.annual_savings.get(k, 0.0) for o in sel), 1) for k in IMPACT_KEYS}
        split[dom]["opportunities"] = len([o for o in opps if o.domain == dom])

    def brief(o: Opportunity) -> dict:
        return dict(id=o.id, title=o.title, technology=o.technology, domain=o.domain, score=o.score,
                    potential_score=o.potential_score, constraint_status=o.constraint_status, next_step=o.next_step,
                    confidence=o.confidence, effort=o.effort, owner_role=o.owner_role,
                    **{f"annual_{k}": round(o.annual_savings.get(k, 0.0), 1) for k in IMPACT_KEYS})

    review = [
        dict(brief(o), reasons=[f"{c.rule_id} {c.category}: {c.reason}" for c in o.constraints],
             alternatives=[c.alternative for c in o.constraints if c.alternative],
             prerequisites=o.prerequisites, next_step_detail=o.next_step_detail)
        for o in sorted(opps, key=lambda x: (x.constraint_status != "blocked", -x.potential_score))
        if o.constraint_status in ("blocked", "conditional")
    ]
    return {
        "current_state": current,
        "footprint_by_domain": by_domain,
        "footprint_by_technology": by_tech,
        "identified_savings": identified,
        "savings_by_domain": split,
        "opportunity_counts": {
            "total": len(opps),
            "clear": sum(o.constraint_status == "clear" for o in opps),
            "conditional": sum(o.constraint_status == "conditional" for o in opps),
            "blocked": sum(o.constraint_status == "blocked" for o in opps),
            "by_next_step": {s: sum(o.next_step == s for o in opps)
                             for s in ("automate", "pilot", "test", "investigate", "monitor", "escalate")},
        },
        "top_opportunities": [brief(o) for o in sorted(actionable, key=lambda x: x.score, reverse=True)[:5]],
        "human_review": review,
        "pathway_comparison": [dict(key=p.key, name=p.name, **p.totals) for p in pathways],
        "mvp_boundary": MVP_BOUNDARY,
    }


def run(data: dict[str, pd.DataFrame], settings: Settings | None = None) -> AnalysisResult:
    settings = settings or load_settings()
    data = coerce_types(data)
    issues = validate(data)
    model = ImpactModel(settings.factors)
    start, end, days = infer_period(data)

    measures, footprint = normalise(data, model, start, end, days, settings.currency)

    assets_df = data.get("assets", pd.DataFrame(columns=["entity"])).set_index("entity")
    ctx = DetectorContext(data=data, assets=assets_df, model=model, rules=settings.rules, period_days=days)
    opps, detector_issues = run_detectors(ctx)
    issues += detector_issues

    assets = _asset_lookup(data)
    factor = model.annual_factor(days)
    for o in opps:
        a = assets.get(o.entity, {})
        o.owner_role, o.service, o.env = a.get("owner_role", ""), a.get("service", ""), a.get("env", "")
        o.annual_baseline = scale(o.baseline, factor)
        o.annual_savings = scale(o.savings, factor)

    apply_constraints(opps, assets, settings.constraints)
    score_all(opps, settings.scoring)
    assign_next_steps(opps, settings.scoring)
    for o in opps:
        o.narrative = explain(o, settings.currency)
    opps.sort(key=lambda o: (o.score, o.potential_score), reverse=True)

    pathways = build_pathways(opps, settings.scoring)
    summary = _summary(footprint, opps, pathways)
    summary["period"] = {"start": str(start.date()), "end": str(end.date()), "days": days,
                         "currency": settings.currency}

    return AnalysisResult(
        measures=measures, footprint=footprint, opportunities=opps, pathways=pathways, summary=summary,
        data_issues=issues, period_start=start, period_end=end, period_days=days, currency=settings.currency,
        assumption_register=dict(settings.factors.get("references", {})),
    )
