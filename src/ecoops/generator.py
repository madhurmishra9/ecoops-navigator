"""Synthetic telemetry generator.

Produces one month of telemetry for an illustrative estate. Each *planted* entity
reproduces one scenario from the EcoOps brief ("Inspiration" section); *control*
entities are healthy and must NOT be flagged. Tests use this catalogue as ground truth.

``generate(seed, applied=...)`` can also simulate post-change telemetry, as if a set
of recommended actions had been implemented. Realised outcomes deliberately differ
from the tool's estimates (owners add safety margin, adoption is partial), so the
post-change verification has something honest to compare.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

PERIOD_START = pd.Timestamp("2026-09-01")
PERIOD_DAYS = 30
REGION = "europe-west2"

PLANTED: dict[str, str] = {
    "rightsize:customer-ingest-daily": "Dataflow batch job runs daily on a large worker pool although CPU and memory utilisation stay low (needs NFT evidence).",
    "region_shift:marketing-events": "Flexible batch job in a higher-carbon region that could run in a lower-carbon region.",
    "region_shift:risk-features": "Same idea, but restricted data must stay in region (blocked by security / data residency).",
    "incremental_processing:daily_customer_snapshot": "BigQuery scheduled load rescans large history although only a small share of source data changes.",
    "event_trigger:finance_dashboard_refresh": "BigQuery refresh runs hourly although its source changes once a day.",
    "ephemeral_cluster:analytics-adhoc": "Dataproc cluster stays provisioned between jobs with very low utilisation.",
    "lifecycle_delete:tmp-landing-zone": "GCS bucket holds stale temporary objects in Standard storage with no lifecycle rule.",
    "lifecycle_delete:audit-logs-archive": "Deleting stale audit logs looks attractive but is blocked by data retention.",
    "storage_class_transition:audit-logs-archive": "Retention-compatible alternative: move stale audit logs to a colder class.",
    "build_on_change:monolith-nightly": "Jenkins timer builds run without any relevant code change.",
    "artifact_retention:monolith-nightly": "Old Jenkins artifacts keep consuming storage.",
    "skip_redundant_deploy:payments-api-cd": "Harness repeatedly deploys the same artifact to the same environment.",
    "schedule_off:nonprod-gke-dev": "Non-production GKE cluster stays fully provisioned overnight and at weekends.",
    "schedule_off:dr-standby-gke": "Idle DR cluster looks attractive to scale down but is blocked by resilience policy.",
    "occupancy_hvac:floor-4": "Office floor with low occupancy while HVAC and lighting follow a fixed full-capacity schedule.",
    "occupancy_hvac:floor-2": "Low-occupancy floor: occupancy-linked HVAC and lighting scheduling.",
    "consolidate_floor:floor-2": "Closing a low-occupancy floor is blocked because it hosts accessibility facilities.",
    "mode_shift:LON-EDI": "Short domestic flights on a rail-feasible route.",
    "print_defaults:london-hq-print": "High single-sided and uncollected printing.",
    "waste_segregation:london-hq-waste": "Low recycling rate in office waste.",
}

CONTROLS: tuple[str, ...] = (
    "payments-recon",
    "orders_incremental",
    "ml-training-ephemeral",
    "curated-datalake",
    "platform-libs-ci",
    "web-frontend-cd",
    "prod-gke-core",
    "floor-6",
    "LON-MAN",
)

# Changes the post-change simulator knows how to apply.
SIMULATABLE: tuple[str, ...] = (
    "rightsize:customer-ingest-daily",
    "incremental_processing:daily_customer_snapshot",
    "event_trigger:finance_dashboard_refresh",
    "ephemeral_cluster:analytics-adhoc",
    "lifecycle_delete:tmp-landing-zone",
    "build_on_change:monolith-nightly",
    "artifact_retention:monolith-nightly",
    "skip_redundant_deploy:payments-api-cd",
    "schedule_off:nonprod-gke-dev",
    "occupancy_hvac:floor-4",
    "mode_shift:LON-EDI",
    "print_defaults:london-hq-print",
    "waste_segregation:london-hq-waste",
)


def _days() -> pd.DatetimeIndex:
    return pd.date_range(PERIOD_START, periods=PERIOD_DAYS, freq="D")


# ---------------------------------------------------------------------------------------------
# Asset register (ownership by ROLE only — the tool never attributes anything to people)
# ---------------------------------------------------------------------------------------------
def _asset(
    entity: str,
    technology: str,
    domain: str,
    owner_role: str,
    service: str,
    env: str = "prod",
    region: str = REGION,
    resilience_tier: str = "tier-2",
    retention_hold: bool = False,
    data_class: str = "internal",
    sla_bound: bool = False,
    accessibility_critical: bool = False,
    schedule_flexible: bool = False,
) -> dict:
    return dict(locals())


def _assets() -> pd.DataFrame:
    a = _asset
    rows = [
        a("customer-ingest-daily", "Dataflow", "digital", "Data Engineering Lead", "Customer 360", data_class="confidential", sla_bound=True),
        a("payments-recon", "Dataflow", "digital", "Payments Data Owner", "Payments", resilience_tier="tier-1", data_class="confidential", sla_bound=True),
        a("risk-features", "Dataflow", "digital", "Risk Analytics Lead", "Credit Risk", data_class="restricted", schedule_flexible=True),
        a("marketing-events", "Dataflow", "digital", "Marketing Analytics Lead", "Marketing Insight", env="analytics", schedule_flexible=True),
        a("daily_customer_snapshot", "BigQuery", "digital", "Analytics Engineering Lead", "Customer 360", data_class="confidential"),
        a("finance_dashboard_refresh", "BigQuery", "digital", "Finance BI Lead", "Finance Reporting"),
        a("orders_incremental", "BigQuery", "digital", "Analytics Engineering Lead", "Orders"),
        a("analytics-adhoc", "Dataproc", "digital", "Analytics Platform Owner", "Shared Analytics", env="analytics"),
        a("ml-training-ephemeral", "Dataproc", "digital", "ML Platform Owner", "Model Training", env="analytics"),
        a("tmp-landing-zone", "GCS", "digital", "Storage Platform Owner", "Ingestion", env="shared"),
        a("audit-logs-archive", "GCS", "digital", "Security Operations Lead", "Audit", retention_hold=True, data_class="confidential"),
        a("curated-datalake", "GCS", "digital", "Data Platform Owner", "Data Lake"),
        a("monolith-nightly", "Jenkins", "digital", "CI/CD Platform Owner", "Core Banking Monolith", env="ci"),
        a("platform-libs-ci", "Jenkins", "digital", "CI/CD Platform Owner", "Platform Libraries", env="ci"),
        a("payments-api-cd", "Harness", "digital", "Application Release Manager", "Payments API", env="ci"),
        a("web-frontend-cd", "Harness", "digital", "Application Release Manager", "Web Frontend", env="ci"),
        a("nonprod-gke-dev", "Kubernetes", "digital", "Kubernetes Platform Owner", "Developer Platform", env="dev"),
        a("dr-standby-gke", "Kubernetes", "digital", "Kubernetes Platform Owner", "Core Services DR", env="dr", resilience_tier="tier-0"),
        a("prod-gke-core", "Kubernetes", "digital", "Kubernetes Platform Owner", "Core Services", resilience_tier="tier-1"),
        a("floor-2", "Office energy", "physical", "Workplace & Facilities Manager", "London HQ", env="workplace", region="uk", accessibility_critical=True),
        a("floor-4", "Office energy", "physical", "Workplace & Facilities Manager", "London HQ", env="workplace", region="uk"),
        a("floor-6", "Office energy", "physical", "Workplace & Facilities Manager", "London HQ", env="workplace", region="uk"),
        a("LON-EDI", "Business travel", "physical", "Travel Programme Manager", "Business Travel", env="workplace", region="uk"),
        a("LON-MAN", "Business travel", "physical", "Travel Programme Manager", "Business Travel", env="workplace", region="uk"),
        a("london-hq-print", "Print", "physical", "Workplace & Facilities Manager", "London HQ", env="workplace", region="uk"),
        a("london-hq-waste", "Waste", "physical", "Workplace & Facilities Manager", "London HQ", env="workplace", region="uk"),
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# Digital sources
# ---------------------------------------------------------------------------------------------
_DATAFLOW = {
    "customer-ingest-daily": dict(workers=20, machine_type="n2-highmem-8", vcpus=8, mem_gb=64, runtime=(95, 8), cpu=(0.18, 0.03), mem=(0.22, 0.04), sla_min=180),
    "payments-recon": dict(workers=6, machine_type="n2-standard-8", vcpus=8, mem_gb=32, runtime=(70, 6), cpu=(0.72, 0.04), mem=(0.64, 0.04), sla_min=120),
    "risk-features": dict(workers=10, machine_type="n2-standard-16", vcpus=16, mem_gb=64, runtime=(120, 12), cpu=(0.62, 0.05), mem=(0.55, 0.05), sla_min=360),
    "marketing-events": dict(workers=4, machine_type="n2-standard-4", vcpus=4, mem_gb=16, runtime=(60, 8), cpu=(0.66, 0.05), mem=(0.50, 0.05), sla_min=480),
}


def _dataflow(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for name, s in _DATAFLOW.items():
        for day in _days():
            cpu = float(np.clip(rng.normal(*s["cpu"]), 0.02, 0.98))
            mem = float(np.clip(rng.normal(*s["mem"]), 0.02, 0.98))
            rows.append(
                dict(
                    job_name=name,
                    run_date=day,
                    region=REGION,
                    workers=s["workers"],
                    machine_type=s["machine_type"],
                    vcpus_per_worker=s["vcpus"],
                    mem_gb_per_worker=s["mem_gb"],
                    runtime_min=round(max(5.0, rng.normal(*s["runtime"])), 1),
                    cpu_util_p95=round(cpu, 3),
                    cpu_util_avg=round(cpu * 0.7, 3),
                    mem_util_p95=round(mem, 3),
                    sla_min=s["sla_min"],
                    status="succeeded",
                )
            )
    df = pd.DataFrame(rows)
    # Telemetry gap: two runs without memory metrics (lowers confidence, shown as missing data).
    gap = df.index[df.job_name == "customer-ingest-daily"][[4, 17]]
    df.loc[gap, "mem_util_p95"] = np.nan
    return df


def _bigquery(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    base = dict(region=REGION)
    for day in _days():
        scanned = float(rng.normal(2.4, 0.08))
        changed = float(abs(rng.normal(0.015, 0.003)))
        rows.append(dict(base, query_name="daily_customer_snapshot", run_ts=day + pd.Timedelta(hours=6), schedule="daily",
                         full_refresh=True, bytes_scanned_tib=round(scanned, 4), source_bytes_changed_tib=round(changed, 5),
                         source_changed_since_last_run=True, slot_ms=int(scanned * 6.0e7)))
        for hour in range(24):
            changed_now = hour == 3
            scanned = float(rng.normal(0.35, 0.01))
            rows.append(dict(base, query_name="finance_dashboard_refresh", run_ts=day + pd.Timedelta(hours=hour), schedule="hourly",
                             full_refresh=False, bytes_scanned_tib=round(scanned, 4),
                             source_bytes_changed_tib=0.02 if changed_now else 0.0,
                             source_changed_since_last_run=changed_now, slot_ms=int(scanned * 6.0e7)))
        scanned = float(rng.normal(0.05, 0.005))
        changed = float(rng.normal(0.03, 0.003))
        rows.append(dict(base, query_name="orders_incremental", run_ts=day + pd.Timedelta(hours=5), schedule="daily",
                         full_refresh=False, bytes_scanned_tib=round(scanned, 4), source_bytes_changed_tib=round(changed, 5),
                         source_changed_since_last_run=True, slot_ms=int(scanned * 6.0e7)))
    return pd.DataFrame(rows)


def _dataproc(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for day in _days():
        busy = float(np.clip(rng.normal(2.5, 0.8), 0.5, 6.0))
        rows.append(dict(cluster="analytics-adhoc", date=day, region=REGION, nodes=30, vcpus_per_node=16, mem_gb_per_node=64,
                         provisioned_hours=24.0, busy_hours=round(busy, 2), busy_cpu_util=0.55))
        busy = float(np.clip(rng.normal(6.0, 1.0), 2.0, 10.0))
        rows.append(dict(cluster="ml-training-ephemeral", date=day, region=REGION, nodes=24, vcpus_per_node=8, mem_gb_per_node=32,
                         provisioned_hours=round(busy + 0.25, 2), busy_hours=round(busy, 2), busy_cpu_util=0.70))
    return pd.DataFrame(rows)


def _gcs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            dict(bucket="tmp-landing-zone", region=REGION, storage_class="STANDARD", size_gb=480000.0, stale_gb_90d=340000.0,
                 objects=2_150_000, lifecycle_rule=False, access_log_coverage=0.95, purpose="temp"),
            dict(bucket="audit-logs-archive", region=REGION, storage_class="STANDARD", size_gb=1200000.0, stale_gb_90d=1100000.0,
                 objects=8_400_000, lifecycle_rule=False, access_log_coverage=0.90, purpose="logs"),
            dict(bucket="curated-datalake", region=REGION, storage_class="STANDARD", size_gb=600000.0, stale_gb_90d=60000.0,
                 objects=1_300_000, lifecycle_rule=True, access_log_coverage=0.90, purpose="datalake"),
        ]
    )


def _jenkins(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for day in _days():
        for hour in (2, 13):
            rows.append(dict(pipeline="monolith-nightly", build_ts=day + pd.Timedelta(hours=hour), region=REGION, trigger="timer",
                             code_changed=bool(rng.random() < 0.2), duration_min=round(max(10.0, rng.normal(55, 5)), 1),
                             executor_vcpus=16, executor_mem_gb=64, artifact_gb=3.5, result="success"))
        for _ in range(int(rng.poisson(6))):
            hour = int(rng.integers(8, 19))
            rows.append(dict(pipeline="platform-libs-ci", build_ts=day + pd.Timedelta(hours=hour), region=REGION, trigger="scm",
                             code_changed=True, duration_min=round(max(2.0, rng.normal(8, 2)), 1),
                             executor_vcpus=4, executor_mem_gb=16, artifact_gb=0.2, result="success"))
    return pd.DataFrame(rows).sort_values(["pipeline", "build_ts"]).reset_index(drop=True)


def _jenkins_artifacts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            dict(pipeline="monolith-nightly", retained_artifacts=420, avg_artifact_gb=3.5, retention_policy="none", storage_media="ssd"),
            dict(pipeline="platform-libs-ci", retained_artifacts=30, avg_artifact_gb=0.2, retention_policy="keep-30", storage_media="ssd"),
        ]
    )


def _harness(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for i, day in enumerate(_days()):
        digest = f"sha256:pay{i:03d}"  # one new payments build a day; 4 scheduled deploys per env
        for env in ("sit", "uat", "preprod"):
            for hour in (7, 11, 15, 19):
                rows.append(dict(pipeline="payments-api-cd", env=env, deploy_ts=day + pd.Timedelta(hours=hour, minutes=5),
                                 artifact_digest=digest, region=REGION, trigger="scheduled",
                                 duration_min=round(max(5.0, rng.normal(25, 3)), 1), vcpus=8))
        for j in range(1 + int(rng.poisson(1))):
            web_digest = f"sha256:web{i:03d}{j}"
            for env in ("dev", "uat"):
                rows.append(dict(pipeline="web-frontend-cd", env=env, deploy_ts=day + pd.Timedelta(hours=9 + 3 * j),
                                 artifact_digest=web_digest, region=REGION, trigger="artifact",
                                 duration_min=round(max(3.0, rng.normal(12, 2)), 1), vcpus=4))
    return pd.DataFrame(rows).sort_values(["pipeline", "env", "deploy_ts"]).reset_index(drop=True)


_K8S = {
    "nonprod-gke-dev": dict(nodes=96, vcpus=8, mem=32, biz=0.45, off=0.04),
    "dr-standby-gke": dict(nodes=24, vcpus=8, mem=32, biz=0.03, off=0.03),
    "prod-gke-core": dict(nodes=120, vcpus=16, mem=64, biz=0.62, off=0.40),
}


def _kubernetes(rng: np.random.Generator) -> pd.DataFrame:
    hours = pd.date_range(PERIOD_START, periods=PERIOD_DAYS * 24, freq="h")
    business = (hours.dayofweek < 5) & (hours.hour >= 8) & (hours.hour < 19)
    frames = []
    for name, s in _K8S.items():
        util = np.where(business, s["biz"], s["off"]) + rng.normal(0, 0.015, len(hours))
        frames.append(pd.DataFrame(dict(cluster=name, ts=hours, region=REGION, nodes=s["nodes"],
                                        vcpus_per_node=s["vcpus"], mem_gb_per_node=s["mem"],
                                        cpu_util=np.clip(util, 0.005, 0.98).round(3))))
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------------------------
# Physical sources
# ---------------------------------------------------------------------------------------------
_FLOORS = {
    "floor-2": dict(cap=120, occ=0.15, hvac=(900, 600), light=(220, 150), schedule="fixed_full_capacity"),
    "floor-4": dict(cap=150, occ=0.28, hvac=(1100, 700), light=(260, 170), schedule="fixed_full_capacity"),
    "floor-6": dict(cap=150, occ=0.72, hvac=(1150, 450), light=(270, 80), schedule="occupancy_linked"),
}


def _facilities(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for floor, s in _FLOORS.items():
        for day in _days():
            weekday = day.dayofweek < 5
            occ = float(np.clip(rng.normal(s["occ"], 0.03), 0.0, 1.0)) if weekday else 0.02
            hvac = s["hvac"][0] if weekday else s["hvac"][1]
            light = s["light"][0] if weekday else s["light"][1]
            rows.append(dict(floor=floor, date=day, site="London HQ", capacity_desks=s["cap"],
                             occupied_desks=round(s["cap"] * occ, 1),
                             hvac_kwh=round(hvac * rng.normal(1.0, 0.04), 1),
                             lighting_kwh=round(light * rng.normal(1.0, 0.03), 1),
                             schedule=s["schedule"]))
    df = pd.DataFrame(rows)
    gaps = df.index[df.floor == "floor-4"][[9, 10, 21]]  # BMS meter gaps
    df.loc[gaps, "hvac_kwh"] = np.nan
    return df


def _travel(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    n = 0

    def trip(route, mode, one_way, cost_per_km):
        nonlocal n
        n += 1
        distance = one_way * 2
        rows.append(dict(trip_id=f"T{n:04d}", month="2026-09", route=route, mode=mode, one_way_km=one_way,
                         distance_km=distance, travellers=1,
                         cost=round(distance * cost_per_km * float(rng.normal(1.0, 0.08)), 2)))

    for _ in range(60):
        trip("LON-EDI", "flight_domestic", 534, 0.32)
    for _ in range(20):
        trip("LON-EDI", "rail", 632, 0.22)
    for _ in range(80):
        trip("LON-MAN", "rail", 262, 0.22)
    return pd.DataFrame(rows)


def _print() -> pd.DataFrame:
    return pd.DataFrame([dict(site="london-hq-print", month="2026-09", pages_printed=420000, duplex_share=0.32,
                              colour_share=0.18, uncollected_share=0.14)])


def _waste() -> pd.DataFrame:
    return pd.DataFrame([dict(site="london-hq-waste", month="2026-09", general_waste_kg=9800.0, recycled_kg=4200.0)])


# ---------------------------------------------------------------------------------------------
# Post-change simulation
# ---------------------------------------------------------------------------------------------
def apply_changes(data: dict[str, pd.DataFrame], applied: Iterable[str], seed: int = 42) -> dict[str, pd.DataFrame]:
    """Return a copy of ``data`` as if the given opportunity ids had been implemented.

    Realised changes are intentionally imperfect versus the tool's recommendation.
    """
    applied = set(applied)
    unknown = applied - set(SIMULATABLE)
    if unknown:
        raise ValueError(f"Cannot simulate: {sorted(unknown)}")
    d = {k: v.copy() for k, v in data.items()}
    rng = np.random.default_rng(seed + 10_000)

    if "rightsize:customer-ingest-daily" in applied:
        df = d["dataflow_jobs"]
        m = df.job_name == "customer-ingest-daily"
        new_workers = 12  # owner keeps extra margin over the recommendation
        ratio = df.loc[m, "workers"] / new_workers
        df.loc[m, "workers"] = new_workers
        for col in ("cpu_util_p95", "cpu_util_avg", "mem_util_p95"):
            df.loc[m, col] = (df.loc[m, col] * ratio).clip(upper=0.95).round(3)
        df.loc[m, "runtime_min"] = (df.loc[m, "runtime_min"] * 1.06).round(1)

    if "incremental_processing:daily_customer_snapshot" in applied:
        df = d["bigquery_jobs"]
        m = df.query_name == "daily_customer_snapshot"
        df.loc[m, "bytes_scanned_tib"] = (df.loc[m, "source_bytes_changed_tib"] * 4.0).round(5)
        df.loc[m, "slot_ms"] = (df.loc[m, "bytes_scanned_tib"] * 6.0e7).astype(int)
        df.loc[m, "full_refresh"] = False

    if "event_trigger:finance_dashboard_refresh" in applied:
        df = d["bigquery_jobs"]
        m = df.query_name == "finance_dashboard_refresh"
        keep = df.source_changed_since_last_run | (pd.to_datetime(df.run_ts).dt.hour == 9)  # plus one safety refresh
        d["bigquery_jobs"] = df[~m | keep].reset_index(drop=True)

    if "ephemeral_cluster:analytics-adhoc" in applied:
        df = d["dataproc_clusters"]
        m = df.cluster == "analytics-adhoc"
        df.loc[m, "provisioned_hours"] = (df.loc[m, "busy_hours"] + 0.75).round(2)

    if "lifecycle_delete:tmp-landing-zone" in applied:
        df = d["gcs_buckets"]
        m = df.bucket == "tmp-landing-zone"
        df.loc[m, "size_gb"] = df.loc[m, "size_gb"] - df.loc[m, "stale_gb_90d"] * 0.9
        df.loc[m, "stale_gb_90d"] = df.loc[m, "stale_gb_90d"] * 0.1
        df.loc[m, "lifecycle_rule"] = True

    if "build_on_change:monolith-nightly" in applied:
        df = d["jenkins_builds"]
        drop = (df.pipeline == "monolith-nightly") & (df.trigger == "timer") & (~df.code_changed)
        d["jenkins_builds"] = df[~drop].reset_index(drop=True)

    if "artifact_retention:monolith-nightly" in applied:
        df = d["jenkins_artifacts"]
        m = df.pipeline == "monolith-nightly"
        df.loc[m, "retained_artifacts"] = 50
        df.loc[m, "retention_policy"] = "keep-50"

    if "skip_redundant_deploy:payments-api-cd" in applied:
        df = d["harness_deployments"]
        prev = df.groupby(["pipeline", "env"])["artifact_digest"].shift(1)
        redundant = (df.pipeline == "payments-api-cd") & (df.artifact_digest == prev)
        d["harness_deployments"] = df[~redundant].reset_index(drop=True)

    if "schedule_off:nonprod-gke-dev" in applied:
        df = d["kubernetes_nodepools"]
        ts = pd.to_datetime(df.ts)
        business = (ts.dt.dayofweek < 5) & (ts.dt.hour >= 8) & (ts.dt.hour < 19)
        m = (df.cluster == "nonprod-gke-dev") & ~business
        ratio = df.loc[m, "nodes"] / 8
        df.loc[m, "nodes"] = 8  # platform team keeps a small overnight pool
        df.loc[m, "cpu_util"] = (df.loc[m, "cpu_util"] * ratio).clip(upper=0.95).round(3)

    if "occupancy_hvac:floor-4" in applied:
        df = d["facilities_daily"]
        m = df.floor == "floor-4"
        occ = df.loc[m, "occupied_desks"] / df.loc[m, "capacity_desks"]
        df.loc[m, "hvac_kwh"] = (df.loc[m, "hvac_kwh"] * (1 - 0.28 * (1 - occ))).round(1)
        df.loc[m, "lighting_kwh"] = (df.loc[m, "lighting_kwh"] * (1 - 0.20 * (1 - occ))).round(1)
        df.loc[m, "schedule"] = "occupancy_linked"

    if "mode_shift:LON-EDI" in applied:
        df = d["travel_trips"]
        flights = df.index[(df.route == "LON-EDI") & (df["mode"] == "flight_domestic")]
        shifted = rng.choice(flights, size=int(len(flights) * 0.6), replace=False)
        df.loc[shifted, "mode"] = "rail"
        df.loc[shifted, "cost"] = (df.loc[shifted, "distance_km"] * 0.22).round(2)

    if "print_defaults:london-hq-print" in applied:
        df = d["print_volumes"]
        df["duplex_share"] = 0.70
        df["uncollected_share"] = 0.04
        df["pages_printed"] = (df["pages_printed"] * 0.78).round(0)

    if "waste_segregation:london-hq-waste" in applied:
        df = d["waste_records"]
        total = df.general_waste_kg + df.recycled_kg
        df["recycled_kg"] = (total * 0.62).round(1)
        df["general_waste_kg"] = (total - df["recycled_kg"]).round(1)

    return d


# ---------------------------------------------------------------------------------------------
def generate(seed: int = 42, applied: Iterable[str] = ()) -> dict[str, pd.DataFrame]:
    """Generate a deterministic synthetic dataset (dict of table name -> DataFrame)."""
    rng = np.random.default_rng(seed)
    data = {
        "assets": _assets(),
        "dataflow_jobs": _dataflow(rng),
        "bigquery_jobs": _bigquery(rng),
        "dataproc_clusters": _dataproc(rng),
        "gcs_buckets": _gcs(),
        "jenkins_builds": _jenkins(rng),
        "jenkins_artifacts": _jenkins_artifacts(),
        "harness_deployments": _harness(rng),
        "kubernetes_nodepools": _kubernetes(rng),
        "facilities_daily": _facilities(rng),
        "travel_trips": _travel(rng),
        "print_volumes": _print(),
        "waste_records": _waste(),
    }
    applied = list(applied)
    return apply_changes(data, applied, seed) if applied else data
