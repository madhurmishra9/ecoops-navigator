# Implementation steps

This is the order the prototype was built in. Use it to rebuild it, extend it, or explain it to judges. Each step ends with a check that proves it works.

---

## Phase 0: Set up (15 min)

1. Create the environment and install the package:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -e ".[app,api,dev]"
   ```
2. Repository layout:
   ```
   src/ecoops/            package (pure Python, pandas + numpy + pyyaml)
   src/ecoops/defaults/   factors.yaml, rules.yaml, constraints.yaml, scoring.yaml
   app/streamlit_app.py   leadership view
   tests/                 pytest suite
   ```
   **Check:** `python -c "import ecoops; print(ecoops.__version__)"`

## Phase 1: Assumption register and thresholds (30 min)

3. Write `factors.yaml`: compute power per vCPU, memory, PUE, slot-hour equivalence, storage Wh per TB-hour, grid intensities, facilities, travel, print and waste factors, and prices. Every block gets a `references` entry, because the brief rewards transparent assumptions.
4. Write `rules.yaml`: one block of thresholds per detector, for example Dataflow p95 CPU ≤ 0.35 and memory ≤ 0.45 over at least 10 runs, sized so the peak run reaches 65%.
5. Write `constraints.yaml`: guardrails keyed on `action_class` plus asset-register attributes. Each one is either `block` or `conditional`, with a reason and an alternative.
6. Write `scoring.yaml`: score weights, impact mix, effort-to-ease map, status multipliers, and next-step thresholds.

   **Check:** `python -c "from ecoops.settings import load_settings; print(load_settings().scoring['weights'])"`

## Phase 2: Synthetic telemetry (1 h)

7. `generator.py`: one seeded generator per source (Dataflow, BigQuery, Dataproc, GCS, Jenkins builds and artifacts, Harness, GKE hourly node pools, facilities daily, travel, print, waste), plus an **asset register** with owner *roles*, resilience tier, retention hold, data class, SLA flag, accessibility flag and schedule flexibility.
8. Plant one entity per brief scenario (`PLANTED`) and one healthy control per technology (`CONTROLS`). Inject realistic gaps: missing memory metrics on two Dataflow runs and BMS meter gaps on one floor.
9. Add `apply_changes()` so the generator can simulate "after" telemetry. Realised changes are deliberately imperfect: owners keep extra margin and adoption is partial.

   **Check:** `ecoops generate --out data && ls data`

## Phase 3: Ingest and normalise (1 h)

10. `ingest.py`: required columns per table (`SCHEMAS`), validation that reports issues instead of crashing, date coercion, and period inference.
11. `impact.py`: compute kWh = (vCPU-h × W(util) + GB-h × kWh/GB-h) × PUE. CO2e = kWh × grid intensity. Cost = list prices. Storage, BigQuery slot-hours and disk follow the same pattern.
12. `normalise.py`: emit long-format **measures** (source, entity, period, metric, value, unit, *provenance*, *confidence*, note) and a per-asset **footprint**, both annualised.

    **Check:** `pytest tests/test_data_layer.py`

## Phase 4: Hotspot detection and root cause (2-3 h)

13. `detectors.py`: one function per hotspot. Each returns `Opportunity` objects containing:
    - evidence items tagged observed / derived / assumed / missing,
    - a before/after impact for the period,
    - confidence that starts from a base and is penalised with stated reasons (telemetry gaps, variance, SLA headroom),
    - missing information needed to act, plus assumptions, effort, proposed action and capacity effect.
14. Detectors never look at constraints, so the trade-off stays visible.

    **Check:** `pytest tests/test_detection.py`. Every planted scenario is detected and no control is flagged.

## Phase 5: Constraints, scoring, recommendations, pathways (1.5 h)

15. `constraints.py`: match rules against the opportunity and the asset register. The result is clear, conditional (prerequisite added) or blocked (reason and alternative).
16. `scoring.py`: log-normalised impact across the portfolio, plus confidence and ease, multiplied by the status multiplier. Store the breakdown and the unconstrained score.
17. `recommend.py`: assign a next step:
    - blocked → **escalate**
    - SLA-bound → **test**
    - high confidence, S effort, clear → **automate**, meaning codify as a guarded policy after owner approval
    - otherwise **pilot**, **investigate** or **monitor** by confidence

    Add a review step for the owner role.
18. `pathways.py`: build three pathways, sequenced into waves (S and clear → wave 1, M or conditional → wave 2, L → wave 3), with one action per asset and no blocked actions:
    - **Quick Wins**: S effort, clear, confidence ≥ 0.7
    - **Digital Efficiency First**: all digital actions plus physical quick wins
    - **Balanced Operations**: top N, about 70/30 digital/physical

    **Check:** `pytest tests/test_decisions.py`

## Phase 6: Leadership view and interfaces (2 h)

19. `pipeline.py`: chain the steps and build the summary: current state, digital/physical split, top opportunities, human-review queue, pathway comparison, assumptions and data quality.
20. `app/streamlit_app.py` has seven tabs:
    - **Overview**: KPIs, footprint by technology, where the reduction sits
    - **Opportunities**: filterable ranked table
    - **Evidence**: provenance badges, score breakdown, confidence reasoning, missing information, constraints
    - **Pathways**
    - **Human review**: blocked and conditional actions with alternatives
    - **Assumptions & data**: register, data quality, measures, downloads
    - **Verification**

    Sidebar sliders change the assumptions and score weights live.
21. `api.py`: read-only FastAPI (`/summary`, `/opportunities`, `/opportunities/{id}`, `/pathways`, `/footprint`, `/assumptions`).
22. `cli.py` and `report.py`: `ecoops generate | analyse | verify`, plus CSV/JSON and a Markdown leadership report.

    **Check:** `pytest tests/test_interfaces.py`. This includes a headless Streamlit `AppTest` render.

## Phase 7: Stretch goal — post-change verification (45 min)

23. `verification.py`: run the pipeline on before and after telemetry, compare estimated with realised annual savings per asset, and give a verdict (on track / under-delivered / over-delivered). On synthetic data, the Dataflow change under-delivers because the owner kept 12 workers instead of 9. That is the honest story the brief asks for.

    **Check:** `ecoops verify --all`

## Phase 8: Quality gates (30 min)

24. `ruff check src tests app` and `pytest -q`. CI runs both in `.github/workflows/ci.yml`.
25. Containerise with the `Dockerfile` (Streamlit on `$PORT`, ready for Cloud Run).

---

## Demo script (5 minutes)

1. **Overview** (WHERE): "584 t CO2e and £2.6M a year across the estate. Digital dominates cost, physical dominates carbon. That is why both sit in one view."
2. **Opportunities** (WHY): sort by score, then open *Scale nonprod-gke-dev down outside business hours*. Show the evidence badges: observed off-hours CPU of 4% against assumed business hours.
3. **Evidence** for *Rightsize customer-ingest-daily*: confidence is reduced by memory-telemetry gaps, the action is conditional on NFT evidence, and the next step is **test**, not "resize".
4. **Human review** (constraints): deleting audit logs is blocked by retention, and the tool offers a retention-compatible ARCHIVE alternative. The DR cluster is blocked by resilience. The accessible floor is blocked by accessibility.
5. **Sidebar** (WHAT COULD CHANGE): drag the office grid factor or PUE. Estimates and ranking update live, because they depend on stated assumptions.
6. **Pathways** (WHAT NEXT): compare Quick Wins, Digital-First and Balanced on CO2e, cost, confidence and approvals, wave by wave.
7. **Verification**: estimated vs realised. Dataflow under-delivered because the owner kept extra margin. That is the feedback loop.

## Connecting real telemetry (after the hackathon)

Write one adapter per source that outputs the tables in `ingest.SCHEMAS`. Nothing downstream changes.

| Table | Real source |
|---|---|
| `dataflow_jobs` | Dataflow Jobs API + Cloud Monitoring (`job/current_num_vcpus`, CPU/memory utilisation) |
| `bigquery_jobs` | `INFORMATION_SCHEMA.JOBS_BY_PROJECT` (`total_bytes_processed`, `total_slot_ms`), partition metadata for change volume |
| `dataproc_clusters` | Dataproc API + Monitoring (YARN allocated vs available) |
| `gcs_buckets` | Storage Insights inventory reports + data-access audit logs |
| `jenkins_builds` / `jenkins_artifacts` | Jenkins REST API (`/api/json?tree=builds[...]`, changeSets) |
| `harness_deployments` | Harness API / audit trail (artifact digest per execution) |
| `kubernetes_nodepools` | GKE usage metering / Cloud Monitoring node metrics |
| `facilities_daily` | BMS sub-meters + badge or desk-booking occupancy |
| `travel_trips`, `print_volumes`, `waste_records` | Travel-management, print-server and waste-contractor exports |
| CO2e factors | Google Cloud Carbon Footprint export and region carbon data; UK Government GHG conversion factors |

Keep the guardrails: read-only service accounts, aggregation by asset and role (never by person), and the human-review queue for anything blocked or conditional.
