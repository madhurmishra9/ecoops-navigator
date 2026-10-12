"""EcoOps Navigator — leadership decision view (Streamlit).

Run:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from ecoops.generator import PLANTED, SIMULATABLE, generate
from ecoops.narrative import llm_explain
from ecoops.pipeline import AnalysisResult, run
from ecoops.report import leadership_markdown
from ecoops.settings import load_settings
from ecoops.verification import verify

st.set_page_config(page_title="EcoOps Navigator", page_icon="🌿", layout="wide")

DOMAIN_COLOURS = {"digital": "#2563eb", "physical": "#d97706"}
STATUS_BADGE = {"clear": "🟢 clear", "conditional": "🟡 conditional", "blocked": "🔴 blocked"}
PROVENANCE_BADGE = {"observed": "🔵 observed", "derived": "🟣 derived", "assumed": "🟠 assumed", "missing": "⚪ missing"}
STEP_BADGE = {"automate": "⚙️ automate", "pilot": "🧪 pilot", "test": "🔬 test", "investigate": "🔎 investigate",
              "monitor": "👁 monitor", "escalate": "🚩 escalate"}

BASE = load_settings()


@st.cache_data(show_spinner="Analysing telemetry…")
def analyse(seed: int, overrides_json: str) -> AnalysisResult:
    overrides = json.loads(overrides_json)
    return run(generate(seed), BASE.with_overrides(**overrides))


@st.cache_data(show_spinner="Simulating post-change telemetry…")
def run_verification(ids: tuple[str, ...], seed: int, overrides_json: str) -> pd.DataFrame:
    return verify(list(ids), seed=seed, settings=BASE.with_overrides(**json.loads(overrides_json)))


def money(v: float, cur: str) -> str:
    sym = {"GBP": "£", "USD": "$", "EUR": "€", "INR": "₹"}.get(cur, "")
    if abs(v) >= 1e6:
        return f"{sym}{v / 1e6:.2f}M"
    if abs(v) >= 1e3:
        return f"{sym}{v / 1e3:.0f}k"
    return f"{sym}{v:.0f}"


def tonnes(kg: float) -> str:
    return f"{kg / 1000:,.1f} t"


# ------------------------------------------------------------------------------------------------
# Sidebar: scenario and assumptions
# ------------------------------------------------------------------------------------------------
with st.sidebar:
    st.title("🌿 EcoOps Navigator")
    st.caption("Decision support. It never changes infrastructure, data, pipelines or facilities, "
               "and never assesses people or teams.")
    seed = int(st.number_input("Synthetic data seed", min_value=1, max_value=9999, value=42))

    st.subheader("Assumptions")
    f = BASE.factors
    cloud = st.slider("Grid intensity europe-west2 (kgCO2e/kWh)", 0.02, 0.40,
                      float(f["grid_intensity_kg_per_kwh"]["europe-west2"]), 0.01)
    office = st.slider("Office grid factor (kgCO2e/kWh)", 0.05, 0.40,
                       float(f["facilities"]["grid_intensity_kg_per_kwh"]), 0.005)
    pue = st.slider("Data-centre PUE", 1.0, 1.6, float(f["compute"]["pue"]), 0.01)
    resp = st.slider("HVAC share that tracks occupancy", 0.10, 0.60,
                     float(f["facilities"]["hvac_occupancy_responsiveness"]), 0.05)

    st.subheader("Score weights")
    w = BASE.scoring["weights"]
    wi = st.slider("Impact", 0.0, 1.0, float(w["impact"]), 0.05)
    wc = st.slider("Confidence", 0.0, 1.0, float(w["confidence"]), 0.05)
    we = st.slider("Ease", 0.0, 1.0, float(w["ease"]), 0.05)
    total_w = (wi + wc + we) or 1.0

overrides = {
    "factors": {"grid_intensity_kg_per_kwh": {"europe-west2": cloud},
                "facilities": {"grid_intensity_kg_per_kwh": office, "hvac_occupancy_responsiveness": resp},
                "compute": {"pue": pue}},
    "scoring": {"weights": {"impact": wi / total_w, "confidence": wc / total_w, "ease": we / total_w}},
}
OVR = json.dumps(overrides, sort_keys=True)
r = analyse(seed, OVR)
s = r.summary
cur = r.currency
opps = r.opportunity_frame()

st.header("EcoOps Navigator — leadership decision view")
st.caption(f"Synthetic telemetry {s['period']['start']} → {s['period']['end']} ({r.period_days} days), annualised. "
           f"**MVP boundary:** {s['mvp_boundary']}")

tabs = st.tabs(["Overview", "Opportunities", "Evidence", "Pathways", "Human review", "Assumptions & data", "Verification"])

# ------------------------------------------------------------------------------------------------
with tabs[0]:
    cs, ids, cnt = s["current_state"], s["identified_savings"], s["opportunity_counts"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Annual footprint", tonnes(cs["annual_co2e_kg"]) + " CO2e", help="All assets in scope, annualised")
    c2.metric("Annual run cost", money(cs["annual_cost"], cur))
    c3.metric("Actionable reduction", tonnes(ids["annual_co2e_kg"]) + " CO2e",
              f"{money(ids['annual_cost'], cur)} / yr", delta_color="off",
              help="One action per asset; blocked actions excluded")
    c4.metric("Need a human decision", f"{cnt['blocked'] + cnt['conditional']}",
              f"{cnt['blocked']} blocked · {cnt['conditional']} conditional", delta_color="off")

    left, right = st.columns([3, 2])
    with left:
        fp = pd.DataFrame(s["footprint_by_technology"])
        metric = st.radio("Footprint by technology", ["annual_co2e_kg", "annual_cost", "annual_energy_kwh"], horizontal=True,
                          format_func={"annual_co2e_kg": "CO2e (kg)", "annual_cost": f"Cost ({cur})",
                                       "annual_energy_kwh": "Energy (kWh)"}.get)
        fig = px.bar(fp.sort_values(metric), x=metric, y="technology", color="domain", orientation="h",
                     color_discrete_map=DOMAIN_COLOURS, labels={metric: "", "technology": ""})
        fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), legend_title_text="")
        st.plotly_chart(fig, width="stretch")
    with right:
        split = pd.DataFrame([{"domain": d, **v} for d, v in s["savings_by_domain"].items()])
        st.markdown("**Where the actionable reduction sits**")
        for col, label in (("annual_co2e_kg", "CO2e"), ("annual_cost", "Cost")):
            fig = px.pie(split, values=col, names="domain", hole=0.55, color="domain",
                         color_discrete_map=DOMAIN_COLOURS)
            fig.update_layout(height=180, margin=dict(l=0, r=0, t=20, b=0), title=label, showlegend=False)
            st.plotly_chart(fig, width="stretch")
        st.caption("Digital dominates cost; physical tends to dominate CO2e because cloud energy per £ is low. "
                   "That is why both appear in one decision view.")

    st.subheader("Top opportunities")
    top = pd.DataFrame(s["top_opportunities"])
    top["next_step"] = top["next_step"].map(STEP_BADGE)
    top["constraint_status"] = top["constraint_status"].map(STATUS_BADGE)
    st.dataframe(top[["score", "title", "domain", "annual_co2e_kg", "annual_cost", "confidence", "constraint_status",
                      "next_step", "owner_role"]], hide_index=True, width="stretch",
                 column_config={"score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
                                "annual_co2e_kg": st.column_config.NumberColumn("kgCO2e/yr", format="%.0f"),
                                "annual_cost": st.column_config.NumberColumn(f"{cur}/yr", format="%.0f")})

# ------------------------------------------------------------------------------------------------
with tabs[1]:
    f1, f2, f3, f4 = st.columns(4)
    dom = f1.multiselect("Domain", sorted(opps.domain.unique()), default=sorted(opps.domain.unique()))
    tech = f2.multiselect("Technology", sorted(opps.technology.unique()), default=sorted(opps.technology.unique()))
    stat = f3.multiselect("Status", ["clear", "conditional", "blocked"], default=["clear", "conditional", "blocked"])
    step = f4.multiselect("Next step", sorted(opps.next_step.unique()), default=sorted(opps.next_step.unique()))
    view = opps[opps.domain.isin(dom) & opps.technology.isin(tech) & opps.constraint_status.isin(stat)
                & opps.next_step.isin(step)].copy()
    view["constraint_status"] = view["constraint_status"].map(STATUS_BADGE)
    view["next_step"] = view["next_step"].map(STEP_BADGE)
    st.dataframe(
        view[["score", "potential_score", "title", "technology", "root_cause", "annual_energy_kwh", "annual_co2e_kg",
              "annual_cost", "saving_pct", "effort", "confidence", "constraint_status", "next_step", "owner_role"]],
        hide_index=True, width="stretch", height=520,
        column_config={
            "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
            "potential_score": st.column_config.NumberColumn("Unconstrained", format="%.0f",
                                                             help="Score before constraints are applied"),
            "annual_energy_kwh": st.column_config.NumberColumn("kWh/yr", format="%.0f"),
            "annual_co2e_kg": st.column_config.NumberColumn("kgCO2e/yr", format="%.0f"),
            "annual_cost": st.column_config.NumberColumn(f"{cur}/yr", format="%.0f"),
            "saving_pct": st.column_config.NumberColumn("% of asset", format="%.0f%%"),
        })
    st.download_button("Download opportunities (CSV)", view.to_csv(index=False), "ecoops_opportunities.csv", "text/csv")
    st.caption("Scores rank actions on assets. Ownership is by role; no individual or team is assessed.")

# ------------------------------------------------------------------------------------------------
with tabs[2]:
    labels = {o.id: f"{o.score:5.1f} · {o.title}" for o in r.opportunities}
    choice = st.selectbox("Opportunity", list(labels), format_func=labels.get)
    o = r.get(choice)
    st.subheader(o.title)
    a, b, c, d = st.columns(4)
    a.metric("EcoOps score", f"{o.score:.0f}", f"unconstrained {o.potential_score:.0f}" if o.score != o.potential_score else None,
             delta_color="off")
    b.metric("Confidence", f"{o.confidence:.2f}")
    c.metric("Status", STATUS_BADGE[o.constraint_status])
    d.metric("Next step", STEP_BADGE[o.next_step])

    if st.toggle("Rephrase with LLM (uses ECOOPS_LLM_URL if set; falls back to template)", value=False):
        st.info(llm_explain(o, currency=cur))
    else:
        st.info(o.narrative)

    left_col, right_col = st.columns([3, 2])
    with left_col:
        st.markdown("**Evidence**")
        ev = pd.DataFrame([{"Evidence": e.label, "Value": str(e.value), "Unit": e.unit,
                            "Provenance": PROVENANCE_BADGE[e.provenance], "Source": e.source} for e in o.evidence])
        st.dataframe(ev, hide_index=True, width="stretch")
        st.markdown(f"**Proposed action:** {o.proposed_action}")
        st.markdown(f"**Capacity effect:** {o.capacity_effect}")
        st.markdown(f"**Next step:** {o.next_step_detail}")
        st.markdown(f"**Review:** {o.review_step}")
    with right_col:
        st.markdown("**Indicative annual effect**")
        eff = pd.DataFrame({"Metric": ["Energy (kWh)", "CO2e (kg)", f"Cost ({cur})"],
                            "Baseline": [o.annual_baseline[k] for k in ("energy_kwh", "co2e_kg", "cost")],
                            "Saving": [o.annual_savings[k] for k in ("energy_kwh", "co2e_kg", "cost")]})
        st.dataframe(eff.round(0), hide_index=True, width="stretch")
        bd = o.score_breakdown
        sc = pd.DataFrame({"part": ["Impact", "Confidence", "Ease"],
                           "points": [bd["impact_points"], bd["confidence_points"], bd["ease_points"]]})
        fig = px.bar(sc, x="points", y="part", orientation="h", text="points")
        fig.update_layout(height=170, margin=dict(l=0, r=0, t=25, b=0),
                          title=f"Score = {bd['raw_score']} × {bd['constraint_multiplier']} (constraint)")
        st.plotly_chart(fig, width="stretch")
        st.markdown("**Confidence reasoning**")
        for reason in o.confidence_reasons:
            st.markdown(f"- {reason}")
        st.markdown("**Missing information**")
        for m in o.missing_information:
            st.markdown(f"- ⚪ {m}")
        st.markdown("**Assumptions**")
        for m in o.assumptions:
            st.markdown(f"- 🟠 {m}")
        if o.constraints:
            st.markdown("**Constraints**")
            for c_ in o.constraints:
                st.markdown(f"- `{c_.rule_id}` **{c_.category}** ({c_.effect}): {c_.reason}"
                            + (f" — *alternative:* {c_.alternative}" if c_.alternative else ""))

# ------------------------------------------------------------------------------------------------
with tabs[3]:
    comp = pd.DataFrame(s["pathway_comparison"])
    m1, m2 = st.columns([2, 3])
    with m1:
        st.dataframe(comp[["name", "actions", "digital_actions", "physical_actions", "annual_co2e_kg", "annual_cost",
                           "mean_confidence", "needs_approval_or_test"]],
                     hide_index=True, width="stretch",
                     column_config={"annual_co2e_kg": st.column_config.NumberColumn("kgCO2e/yr", format="%.0f"),
                                    "annual_cost": st.column_config.NumberColumn(f"{cur}/yr", format="%.0f")})
    with m2:
        long = comp.melt(id_vars="name", value_vars=["annual_co2e_kg", "annual_cost"], var_name="metric")
        fig = px.bar(long, x="name", y="value", facet_col="metric", color="name", labels={"name": "", "value": ""})
        fig.update_yaxes(matches=None, showticklabels=True)
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0), showlegend=False)
        st.plotly_chart(fig, width="stretch")
    for p in r.pathways:
        with st.expander(f"{p.name} — {p.totals['actions']} actions · {tonnes(p.totals['annual_co2e_kg'])} CO2e · "
                         f"{money(p.totals['annual_cost'], cur)}/yr"):
            st.caption(p.description)
            if p.actions:
                df = pd.DataFrame(p.actions)
                df["next_step"] = df["next_step"].map(STEP_BADGE)
                st.dataframe(df[["wave_label", "title", "domain", "effort", "confidence", "next_step", "annual_co2e_kg",
                                 "annual_cost", "owner_role"]], hide_index=True, width="stretch")

# ------------------------------------------------------------------------------------------------
with tabs[4]:
    st.markdown("Actions that look attractive on carbon or cost but need a human decision. "
                "Blocked actions score 0 and are never put on a pathway.")
    for h in s["human_review"]:
        icon = "🔴" if h["constraint_status"] == "blocked" else "🟡"
        with st.container(border=True):
            st.markdown(f"{icon} **{h['title']}** · unconstrained score {h['potential_score']:.0f} · "
                        f"{tonnes(h['annual_co2e_kg'])} CO2e · {money(h['annual_cost'], cur)}/yr · owner: {h['owner_role']}")
            for reason in h["reasons"]:
                st.markdown(f"- {reason}")
            for alt in h["alternatives"]:
                st.markdown(f"- ↪️ *Alternative:* {alt}")
            if h["prerequisites"]:
                st.markdown(f"- ✅ *Prerequisites:* {'; '.join(h['prerequisites'])}")

# ------------------------------------------------------------------------------------------------
with tabs[5]:
    st.subheader("Assumption register")
    st.dataframe(pd.DataFrame([{"Area": k, "Assumption / reference": v} for k, v in r.assumption_register.items()]),
                 hide_index=True, width="stretch")
    st.subheader("Data quality")
    for issue in r.data_issues or ["No issues found."]:
        st.markdown(f"- {issue}")
    st.subheader("Normalised measures")
    prov = st.multiselect("Provenance", ["observed", "derived", "assumed", "missing"],
                          default=["observed", "derived", "assumed", "missing"])
    st.dataframe(r.measures[r.measures.provenance.isin(prov)], hide_index=True, width="stretch", height=320)
    st.download_button("Download measures (CSV)", r.measures.to_csv(index=False), "ecoops_measures.csv", "text/csv")
    st.download_button("Download leadership report (Markdown)", leadership_markdown(r), "ecoops_leadership_report.md",
                       "text/markdown")
    with st.expander("Synthetic scenario catalogue (ground truth used by the tests)"):
        st.dataframe(pd.DataFrame([{"opportunity": k, "scenario": v} for k, v in PLANTED.items()]),
                     hide_index=True, width="stretch")

# ------------------------------------------------------------------------------------------------
with tabs[6]:
    st.markdown("**Post-change verification.** Simulates implementing selected actions on the synthetic estate "
                "(owners add margin, adoption is partial) and compares realised with estimated annual savings.")
    available = [i for i in SIMULATABLE if r.get(i) is not None]
    chosen = st.multiselect("Implemented actions", available, default=available[:6])
    if st.button("Run verification", type="primary") and chosen:
        res = run_verification(tuple(chosen), seed, OVR)
        st.dataframe(res[["entity", "technology", "estimated_co2e_kg", "realised_co2e_kg", "realisation_co2e_kg",
                          "estimated_cost", "realised_cost", "realisation_cost", "verdict"]],
                     hide_index=True, width="stretch")
        long = res.melt(id_vars="entity", value_vars=["estimated_cost", "realised_cost"], var_name="kind")
        fig = px.bar(long, x="entity", y="value", color="kind", barmode="group", labels={"value": f"{cur}/yr", "entity": ""})
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), legend_title_text="")
        st.plotly_chart(fig, width="stretch")
