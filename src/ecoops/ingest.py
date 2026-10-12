"""Input contract: required tables/columns, CSV load/save and period inference.

Real telemetry (billing export, Cloud Monitoring, Jenkins/Harness APIs, BMS meters,
travel and facilities systems) is mapped onto these tables by an adapter; the rest of
the pipeline only ever sees this contract.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SCHEMAS: dict[str, list[str]] = {
    "assets": ["entity", "technology", "domain", "owner_role", "service", "env", "region", "resilience_tier",
               "retention_hold", "data_class", "sla_bound", "accessibility_critical", "schedule_flexible"],
    "dataflow_jobs": ["job_name", "run_date", "region", "workers", "machine_type", "vcpus_per_worker",
                      "mem_gb_per_worker", "runtime_min", "cpu_util_p95", "cpu_util_avg", "mem_util_p95", "sla_min"],
    "bigquery_jobs": ["query_name", "run_ts", "region", "schedule", "full_refresh", "bytes_scanned_tib",
                      "source_bytes_changed_tib", "source_changed_since_last_run", "slot_ms"],
    "dataproc_clusters": ["cluster", "date", "region", "nodes", "vcpus_per_node", "mem_gb_per_node",
                          "provisioned_hours", "busy_hours", "busy_cpu_util"],
    "gcs_buckets": ["bucket", "region", "storage_class", "size_gb", "stale_gb_90d", "lifecycle_rule",
                    "access_log_coverage", "purpose"],
    "jenkins_builds": ["pipeline", "build_ts", "region", "trigger", "code_changed", "duration_min",
                       "executor_vcpus", "executor_mem_gb"],
    "jenkins_artifacts": ["pipeline", "retained_artifacts", "avg_artifact_gb", "retention_policy", "storage_media"],
    "harness_deployments": ["pipeline", "env", "deploy_ts", "artifact_digest", "region", "duration_min", "vcpus"],
    "kubernetes_nodepools": ["cluster", "ts", "region", "nodes", "vcpus_per_node", "mem_gb_per_node", "cpu_util"],
    "facilities_daily": ["floor", "date", "capacity_desks", "occupied_desks", "hvac_kwh", "lighting_kwh", "schedule"],
    "travel_trips": ["trip_id", "route", "mode", "one_way_km", "distance_km", "travellers", "cost"],
    "print_volumes": ["site", "pages_printed", "duplex_share", "uncollected_share"],
    "waste_records": ["site", "general_waste_kg", "recycled_kg"],
}

DATE_COLUMNS: dict[str, list[str]] = {
    "dataflow_jobs": ["run_date"],
    "bigquery_jobs": ["run_ts"],
    "dataproc_clusters": ["date"],
    "jenkins_builds": ["build_ts"],
    "harness_deployments": ["deploy_ts"],
    "kubernetes_nodepools": ["ts"],
    "facilities_daily": ["date"],
}


def validate(data: dict[str, pd.DataFrame]) -> list[str]:
    """Return human-readable data-quality issues (empty list = contract satisfied)."""
    issues: list[str] = []
    for table, columns in SCHEMAS.items():
        if table not in data:
            issues.append(f"Missing table '{table}': related detectors will be skipped.")
            continue
        df = data[table]
        missing = [c for c in columns if c not in df.columns]
        if missing:
            issues.append(f"Table '{table}' is missing columns {missing}.")
        if df.empty:
            issues.append(f"Table '{table}' is empty.")
        nulls = {c: int(df[c].isna().sum()) for c in columns if c in df.columns and df[c].isna().any()}
        if nulls:
            detail = ", ".join(f"{c}={n}" for c, n in nulls.items())
            issues.append(f"Table '{table}' has missing values ({detail}); affected flags carry lower confidence.")
    return issues


def coerce_types(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out = {}
    for name, df in data.items():
        df = df.copy()
        for col in DATE_COLUMNS.get(name, []):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
        out[name] = df
    return out


def load_csv_dir(path: str | Path) -> dict[str, pd.DataFrame]:
    path = Path(path)
    data = {p.stem: pd.read_csv(p) for p in sorted(path.glob("*.csv"))}
    if not data:
        raise FileNotFoundError(f"No CSV files found in {path}")
    return coerce_types(data)


def save_csv_dir(data: dict[str, pd.DataFrame], path: str | Path) -> list[Path]:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    written = []
    for name, df in data.items():
        target = path / f"{name}.csv"
        df.to_csv(target, index=False)
        written.append(target)
    return written


def infer_period(data: dict[str, pd.DataFrame]) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    """Analysis window from the time-series tables (start, end, length in days)."""
    starts, ends = [], []
    for table, cols in DATE_COLUMNS.items():
        df = data.get(table)
        if df is None or df.empty:
            continue
        for col in cols:
            if col in df.columns:
                series = pd.to_datetime(df[col])
                starts.append(series.min())
                ends.append(series.max())
    if not starts:
        today = pd.Timestamp.today().normalize()
        return today - pd.Timedelta(days=29), today, 30
    start = min(starts).normalize()
    end = max(ends).normalize()
    return start, end, int((end - start).days) + 1
