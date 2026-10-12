# EcoOps Navigator

An explainable decision-support prototype. It helps technology, facilities, finance and sustainability leaders move from fragmented operational telemetry to a **prioritised portfolio of feasible actions**. Digital operations get the strongest analytical emphasis (~70%), and physical operations add the other ~30%.

It answers the five questions in the brief:

| Question | Where it is answered |
|---|---|
| **WHERE** are the largest opportunities? | Footprint by technology and the ranked opportunity portfolio |
| **WHY** are they occurring? | A root cause for every flag, backed by evidence tagged *observed / derived / assumed / missing* |
| **WHAT** could reduce resource use safely? | Proposed action, capacity effect, and a constraint engine (resilience, security, retention, accessibility, performance, change control) |
| **WHAT COULD CHANGE**? | Indicative energy, CO2e and cost effects under an editable assumption register, with live sliders in the UI |
| **WHAT NEXT**? | automate / investigate / test / pilot / monitor / escalate, an owner role, a review step, and three sequenced pathways |

> **MVP boundary:** decision-quality prioritisation only. It is not production-grade carbon accounting, and it never resizes infrastructure, stops workloads, deletes data, changes pipelines or facilities, or assesses employee or team performance.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[app,api,dev]"

streamlit run app/streamlit_app.py          # leadership dashboard
ecoops analyse --out reports                # CLI: CSV/JSON exports + leadership_report.md
ecoops verify --all                         # post-change verification (stretch goal)
uvicorn ecoops.api:app --reload             # read-only REST API on :8000/docs
pytest -q                                   # 32 tests incl. ground-truth detection
```

Docker: `docker build -t ecoops . && docker run -p 8080:8080 ecoops`

## What it detects (synthetic estate, Sept 2026)

| Brief scenario | Detector | Typical outcome |
|---|---|---|
| Over-provisioned Dataflow batch job | `dataflow_rightsizing` | Conditional, next step **test** (NFT evidence required) |
| BigQuery rescans history for a small change | `bigquery_scans` | Incremental MERGE |
| BigQuery refresh on unchanged source | `bigquery_schedule` | Event-driven trigger |
| Idle Dataproc cluster between jobs | `dataproc_idle` | Ephemeral / serverless |
| Stale GCS data without a lifecycle rule | `gcs_lifecycle` | Delete rule, or class transition when retention applies |
| Jenkins builds with no code change, old artifacts | `jenkins_builds`, `jenkins_artifacts` | Build on change, discarder |
| Harness redeploys the same artifact | `harness_deployments` | Skip on unchanged digest |
| Non-prod GKE running overnight and at weekends | `kubernetes_offhours` | Scheduled scale-down |
| Low-occupancy floor on a fixed HVAC schedule | `facilities_occupancy` | Occupancy-linked BMS |
| Attractive action blocked by a constraint | constraint engine | DR cluster (resilience), audit logs (retention), restricted data (residency), accessible floor (accessibility) |
| Travel, print, waste | `travel_mode_shift`, `print_efficiency`, `waste_segregation` | Behavioural defaults |
| Flexible batch in a high-carbon region | `region_shift` | Investigate; blocked for restricted data |

Healthy *control* assets exist for each technology. The tests assert that every planted scenario is found and that no control is flagged.

## Architecture

```
 telemetry (CSV / adapters)          config/*.yaml (assumptions, thresholds, constraints, weights)
          │                                         │
          ▼                                         ▼
 ingest ──► normalise ──► detectors ──► constraints ──► scoring ──► recommend ──► pathways ──► summary
 (contract) (measures +   (14 rule-      (block /        (0-100,     (next step,   (Quick Wins,  (leadership
            footprint)    based)         conditional)    decomposed)  owner role)   Digital-First, view)
                                                                                    Balanced)
          └──────────────► Streamlit UI · FastAPI · CLI · Markdown report · verification
```

| Module | Responsibility |
|---|---|
| `generator.py` | Seeded synthetic telemetry with planted scenarios and controls, plus post-change simulation |
| `ingest.py` | Input contract, validation, CSV I/O, period inference |
| `normalise.py` | Long-format measures (source, period, unit, provenance, confidence) and per-asset footprint |
| `impact.py` | Energy, CO2e and cost model. Every coefficient comes from `factors.yaml` |
| `detectors.py` | 14 deterministic hotspot detectors with evidence, confidence reasoning and missing information |
| `constraints.py` | Policy guardrails with reasons and alternatives |
| `scoring.py` | EcoOps Opportunity Score (impact x confidence x ease x constraint multiplier) |
| `recommend.py` | Next step and review step per opportunity |
| `pathways.py` | Three pathways, sequenced into waves, one action per asset, blocked actions excluded |
| `pipeline.py` | Orchestration and leadership summary |
| `verification.py` | Estimated vs realised comparison |
| `narrative.py` | Template explanations, with an optional grounded LLM rephrase (`ECOOPS_LLM_URL`) |

### EcoOps Opportunity Score

```
impact = Σ mix_k · log1p(saving_k) / log1p(max saving_k)      k ∈ {CO2e 0.5, cost 0.3, energy 0.2}
score  = 100 · (0.55·impact + 0.25·confidence + 0.20·ease[S=1, M=0.6, L=0.3]) × status (clear 1, conditional 0.85, blocked 0)
```

Every score is shown with its breakdown. Blocked actions keep an *unconstrained* score so leaders can see what is being given up. The score ranks actions on assets, never people.

## Configuration

Packaged defaults live in `src/ecoops/defaults/`. To override any subset, pass a directory with `--config` or set `ECOOPS_CONFIG_DIR`:

```yaml
# my-config/factors.yaml
grid_intensity_kg_per_kwh:
  europe-west2: 0.12
```

All factors are **illustrative assumptions** with references. Replace them with organisation-approved values before using any number outside a prototype.

See **[IMPLEMENTATION.md](IMPLEMENTATION.md)** for the step-by-step build, the demo script, and how to connect real telemetry.
