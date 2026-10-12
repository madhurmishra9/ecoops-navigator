"""Leadership report (Markdown) and file exports."""

from __future__ import annotations

import json
from pathlib import Path

from .pipeline import AnalysisResult
from .utils import fmt_qty, to_jsonable


def leadership_markdown(r: AnalysisResult) -> str:
    s = r.summary
    cur, ids = s["current_state"], s["identified_savings"]
    c = r.currency
    lines = [
        "# EcoOps Navigator — Leadership Summary",
        "",
        f"Period analysed: {s['period']['start']} to {s['period']['end']} ({r.period_days} days), annualised.",
        "",
        f"> **MVP boundary:** {s['mvp_boundary']}",
        "",
        "## Current state (annualised)",
        "",
        "| Domain | Energy | CO2e | Cost |",
        "|---|---|---|---|",
    ]
    for d in s["footprint_by_domain"]:
        lines.append(f"| {d['domain']} | {fmt_qty(d['annual_energy_kwh'], 'kWh')} | "
                     f"{fmt_qty(d['annual_co2e_kg'] / 1000, 't')} | {fmt_qty(d['annual_cost'], c)} |")
    lines += [
        f"| **Total** | **{fmt_qty(cur['annual_energy_kwh'], 'kWh')}** | **{fmt_qty(cur['annual_co2e_kg'] / 1000, 't')}** "
        f"| **{fmt_qty(cur['annual_cost'], c)}** |",
        "",
        "## Identified opportunities (actionable, one action per asset)",
        "",
        f"Indicative annual reduction under stated assumptions: **{fmt_qty(ids['annual_co2e_kg'] / 1000, 'tCO2e')}**, "
        f"**{fmt_qty(ids['annual_cost'], c)}**, **{fmt_qty(ids['annual_energy_kwh'], 'kWh')}**.",
        "",
        "| # | Opportunity | Score | Status | Next step | CO2e/yr | Cost/yr | Confidence | Owner role |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, o in enumerate([o for o in r.opportunities if o.constraint_status != "blocked"], 1):
        lines.append(f"| {i} | {o.title} | {o.score:.0f} | {o.constraint_status} | {o.next_step} | "
                     f"{fmt_qty(o.annual_savings['co2e_kg'], 'kg')} | {fmt_qty(o.annual_savings['cost'], c)} | "
                     f"{o.confidence:.2f} | {o.owner_role} |")
    lines += ["", "## Pathway comparison", "",
              "| Pathway | Actions (digital/physical) | CO2e/yr | Cost/yr | Mean confidence | Need approval/test |",
              "|---|---|---|---|---|---|"]
    for p in s["pathway_comparison"]:
        lines.append(f"| {p['name']} | {p['actions']} ({p['digital_actions']}/{p['physical_actions']}) | "
                     f"{fmt_qty(p['annual_co2e_kg'] / 1000, 't')} | {fmt_qty(p['annual_cost'], c)} | "
                     f"{p['mean_confidence']:.2f} | {p['needs_approval_or_test']} |")
    lines += ["", "## Decisions requiring human review", ""]
    for h in s["human_review"]:
        lines.append(f"- **{h['title']}** — {h['constraint_status']}. " + " ".join(h["reasons"]))
        for alt in h["alternatives"]:
            lines.append(f"  - Alternative: {alt}")
    lines += ["", "## Assumptions", ""]
    for k, v in r.assumption_register.items():
        lines.append(f"- **{k}:** {v}")
    if r.data_issues:
        lines += ["", "## Data quality", ""] + [f"- {i}" for i in r.data_issues]
    lines += ["", "## Evidence per opportunity", ""]
    for o in r.opportunities:
        lines += [f"### {o.title}", "", o.narrative, "",
                  "| Evidence | Value | Provenance |", "|---|---|---|"]
        lines += [f"| {e.label} | {e.value} {e.unit} | {e.provenance} |" for e in o.evidence]
        lines += ["", f"Missing information: {'; '.join(o.missing_information) or 'none'}", ""]
    return "\n".join(lines) + "\n"


def export(r: AnalysisResult, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "opportunities.csv": lambda p: r.opportunity_frame().to_csv(p, index=False),
        "opportunities.json": lambda p: p.write_text(json.dumps(to_jsonable([o.to_dict() for o in r.opportunities]), indent=2)),
        "pathways.json": lambda p: p.write_text(json.dumps(to_jsonable([pw.to_dict() for pw in r.pathways]), indent=2)),
        "summary.json": lambda p: p.write_text(json.dumps(to_jsonable(r.summary), indent=2)),
        "measures.csv": lambda p: r.measures.to_csv(p, index=False),
        "footprint.csv": lambda p: r.footprint.to_csv(p, index=False),
        "leadership_report.md": lambda p: p.write_text(leadership_markdown(r), encoding="utf-8"),
    }
    written = []
    for name, write in files.items():
        path = out / name
        write(path)
        written.append(path)
    return written
