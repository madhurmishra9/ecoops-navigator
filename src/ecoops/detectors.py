"""Hotspot detectors.

Each detector is a small, deterministic function: telemetry + thresholds in, a list of
Opportunity objects out. Every flag carries:

* evidence, labelled observed / derived / assumed / missing,
* a before/after impact estimate for the analysis period,
* a confidence value with the reasons that moved it,
* the information that would be needed to act with more certainty.

Detectors never look at constraints (resilience, retention, security, accessibility);
those are applied afterwards by ``constraints.py`` so the trade-off stays visible.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .impact import DAYS_PER_MONTH, ImpactModel, diff
from .models import Evidence, Opportunity


@dataclass
class DetectorContext:
    data: dict[str, pd.DataFrame]
    assets: pd.DataFrame  # indexed by entity
    model: ImpactModel
    rules: dict[str, Any]
    period_days: int

    def table(self, name: str) -> pd.DataFrame:
        return self.data.get(name, pd.DataFrame())

    def asset(self, entity: str) -> dict[str, Any]:
        if entity not in self.assets.index:
            return {}
        return {k: (v.item() if isinstance(v, np.generic) else v) for k, v in self.assets.loc[entity].to_dict().items()}


class _Confidence:
    def __init__(self, base: float, reason: str):
        self.value = base
        self.reasons = [f"Start {base:.2f}: {reason}"]

    def penalise(self, condition: bool, amount: float, reason: str) -> None:
        if condition:
            self.value -= amount
            self.reasons.append(f"-{amount:.2f}: {reason}")

    @property
    def final(self) -> float:
        return round(float(min(0.95, max(0.2, self.value))), 2)


def _opp(before: dict, after: dict, conf: _Confidence, **kwargs) -> Opportunity:
    return Opportunity(baseline=before, savings=diff(before, after), confidence=conf.final,
                       confidence_reasons=conf.reasons, **kwargs)


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


# =================================================================================================
# Digital detectors
# =================================================================================================
def dataflow_rightsizing(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["dataflow_rightsizing"], ctx.model
    out = []
    for name, g in ctx.table("dataflow_jobs").groupby("job_name"):
        if len(g) < r["min_runs"]:
            continue
        cpu_med, mem_med = g.cpu_util_p95.median(), g.mem_util_p95.median()
        if not (cpu_med <= r["cpu_p95_max"] and mem_med <= r["mem_p95_max"]):
            continue
        cpu_peak, mem_peak = g.cpu_util_p95.max(), g.mem_util_p95.max()
        workers = int(g.workers.mode().iloc[0])
        need = max(cpu_peak, mem_peak) / r["target_utilisation"]
        new_workers = max(1, math.ceil(workers * need))
        if new_workers >= workers:
            continue
        penalty = r["runtime_penalty"]
        region = g.region.iloc[0]
        vcpu_h = (g.workers * g.vcpus_per_worker * g.runtime_min / 60).sum()
        mem_h = (g.workers * g.mem_gb_per_worker * g.runtime_min / 60).sum()
        util = float(g.cpu_util_avg.mean())
        ratio = new_workers / workers * (1 + penalty)
        before = m.impact(m.compute_kwh(vcpu_h, mem_h, util), m.compute_cost(vcpu_h, mem_h), region)
        after = m.impact(m.compute_kwh(vcpu_h * ratio, mem_h * ratio, min(0.95, util / ratio)),
                         m.compute_cost(vcpu_h * ratio, mem_h * ratio), region)
        max_rt, sla = float(g.runtime_min.max()), float(g.sla_min.iloc[0])
        headroom = sla / (max_rt * (1 + penalty))
        missing_mem = int(g.mem_util_p95.isna().sum())
        cv = float(g.runtime_min.std() / g.runtime_min.mean())
        low_share = float(((g.cpu_util_p95 <= r["cpu_p95_max"]) & (g.mem_util_p95.fillna(0) <= r["mem_p95_max"])).mean())

        conf = _Confidence(0.85, f"{len(g)} daily runs with utilisation telemetry")
        conf.penalise(missing_mem > 0, 0.10, f"{missing_mem} runs missing memory telemetry")
        conf.penalise(cv > 0.2, 0.10, "runtime varies by more than 20%")
        conf.penalise(headroom < 1.3, 0.15, "SLA headroom below 30% after runtime penalty")

        missing = ["NFT / performance-test evidence for the proposed worker count",
                   "Transformation profile (shuffle, hot keys) and autoscaling history"]
        if missing_mem:
            missing.append(f"Memory utilisation for {missing_mem} runs")
        machine = g.machine_type.iloc[0]
        out.append(_opp(
            before, after, conf,
            detector="dataflow_rightsizing", action_class="rightsize", technology="Dataflow", domain="digital",
            entity=name, title=f"Rightsize Dataflow job {name}: {workers} -> {new_workers} workers",
            root_cause="over-configuration",
            proposed_action=(f"Reduce max workers from {workers} to {new_workers} ({machine}) or enable bounded "
                             f"autoscaling, sized so the peak observed run reaches ~{_pct(r['target_utilisation'])} utilisation."),
            capacity_effect=(f"{workers * int(g.vcpus_per_worker.iloc[0])} -> {new_workers * int(g.vcpus_per_worker.iloc[0])} vCPU; "
                             f"runtime assumed +{_pct(penalty)} (worst case {max_rt * (1 + penalty):.0f} of {sla:.0f} min SLA)"),
            effort="M",
            evidence=[
                Evidence("Runs analysed", len(g), "runs", "observed", "dataflow_jobs"),
                Evidence("Configured pool", f"{workers} x {machine}", "", "observed", "dataflow_jobs"),
                Evidence("Median p95 CPU", round(cpu_med, 3), "ratio", "observed", "dataflow_jobs"),
                Evidence("Median p95 memory", round(mem_med, 3), "ratio", "observed", "dataflow_jobs"),
                Evidence("Peak p95 CPU / memory", f"{cpu_peak:.2f} / {mem_peak:.2f}", "ratio", "observed", "dataflow_jobs"),
                Evidence("Runs below both thresholds", round(low_share, 2), "share", "derived", "dataflow_jobs"),
                Evidence("Proposed workers", new_workers, "workers", "derived", f"peak / target {r['target_utilisation']}"),
                Evidence("SLA headroom after change", round(headroom, 2), "x", "derived", "sla_min / worst runtime"),
                Evidence("Runtime penalty", penalty, "share", "assumed", "rules.yaml"),
                Evidence("Memory telemetry gaps", missing_mem, "runs", "missing" if missing_mem else "observed", "dataflow_jobs"),
            ],
            missing_information=missing,
            assumptions=["Compute power and price coefficients (factors.yaml: compute)",
                         f"Runtime increases by {_pct(penalty)} with fewer workers"],
        ))
    return out


def region_shift(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["region_shift"], ctx.model
    candidates = ctx.model.f.get("low_carbon_regions", [])
    if not candidates:
        return []
    out = []
    for name, g in ctx.table("dataflow_jobs").groupby("job_name"):
        asset = ctx.asset(name)
        if not asset.get("schedule_flexible"):
            continue
        region = g.region.iloc[0]
        best = min(candidates, key=m.grid_intensity)
        cur, target = m.grid_intensity(region), m.grid_intensity(best)
        if best == region or cur <= 0 or 1 - target / cur < r["min_intensity_reduction"]:
            continue
        vcpu_h = (g.workers * g.vcpus_per_worker * g.runtime_min / 60).sum()
        mem_h = (g.workers * g.mem_gb_per_worker * g.runtime_min / 60).sum()
        kwh = m.compute_kwh(vcpu_h, mem_h, float(g.cpu_util_avg.mean()))
        cost = m.compute_cost(vcpu_h, mem_h)
        before, after = m.impact(kwh, cost, region), m.impact(kwh, cost, best)
        conf = _Confidence(0.65, "flexible schedule recorded in asset register")
        conf.penalise(True, 0.05, "egress cost and latency not in telemetry")
        out.append(_opp(
            before, after, conf,
            detector="region_shift", action_class="region_shift", technology="Dataflow", domain="digital", entity=name,
            title=f"Run flexible batch job {name} in lower-carbon region {best}",
            root_cause="carbon-intensive placement",
            proposed_action=f"Move the flexible batch job from {region} to {best} after residency, latency and egress review.",
            capacity_effect="No capacity change; same configuration in another region",
            effort="L",
            evidence=[
                Evidence("Schedule flexibility", True, "", "observed", "asset register"),
                Evidence("Data classification", asset.get("data_class", "unknown"), "", "observed", "asset register"),
                Evidence(f"Grid intensity {region}", cur, "kgCO2e/kWh", "assumed", "factors.yaml"),
                Evidence(f"Grid intensity {best}", target, "kgCO2e/kWh", "assumed", "factors.yaml"),
                Evidence("Job energy in period", round(kwh, 1), "kWh", "derived", "dataflow_jobs"),
                Evidence("Cross-region egress cost", "unknown", "", "missing", ""),
            ],
            missing_information=["Cross-region egress cost and latency to downstream consumers",
                                 "Confirmed data-residency classification for inputs and outputs"],
            assumptions=["Regional grid intensities are illustrative (factors.yaml)", "Energy use unchanged by the move"],
        ))
    return out


def bigquery_scans(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["bigquery_scans"], ctx.model
    out = []
    for name, g in ctx.table("bigquery_jobs").groupby("query_name"):
        if len(g) < r["min_runs"] or g.full_refresh.mean() < 0.5:
            continue
        scanned, changed = float(g.bytes_scanned_tib.sum()), float(g.source_bytes_changed_tib.sum())
        ratio = scanned / max(changed, 1e-6)
        if ratio < r["scan_to_change_ratio_min"]:
            continue
        mult = r["incremental_read_multiplier"]
        after_scanned = min(scanned, changed * mult)
        share = after_scanned / scanned
        slot_ms = float(g.slot_ms.sum())
        region = g.region.iloc[0]
        before = m.impact(m.bigquery_kwh(slot_ms), m.bigquery_cost(scanned), region)
        after = m.impact(m.bigquery_kwh(slot_ms * share), m.bigquery_cost(after_scanned), region)
        conf = _Confidence(0.80, f"{len(g)} runs with bytes-scanned and source-change metrics")
        conf.penalise(g.source_bytes_changed_tib.isna().any(), 0.1, "source change volume incomplete")
        out.append(_opp(
            before, after, conf,
            detector="bigquery_scans", action_class="incremental_processing", technology="BigQuery", domain="digital",
            entity=name, title=f"Make {name} incremental instead of full refresh",
            root_cause="excessive scans / inefficient processing",
            proposed_action="Replace the full-history rebuild with a partition-filtered MERGE of changed partitions "
                            "(or an incremental materialisation), keeping a periodic full reconciliation.",
            capacity_effect=f"Scanned data {scanned:.1f} -> {after_scanned:.2f} TiB per period",
            effort="M",
            evidence=[
                Evidence("Runs analysed", len(g), "runs", "observed", "bigquery_jobs"),
                Evidence("Full-refresh runs", round(float(g.full_refresh.mean()), 2), "share", "observed", "bigquery_jobs"),
                Evidence("Data scanned", round(scanned, 2), "TiB", "observed", "bigquery_jobs"),
                Evidence("Source data changed", round(changed, 3), "TiB", "observed", "bigquery_jobs"),
                Evidence("Scan-to-change ratio", round(ratio, 0), "x", "derived", ""),
                Evidence("Incremental read multiplier", mult, "x changed", "assumed", "rules.yaml"),
            ],
            missing_information=["Whether downstream consumers rely on full-snapshot semantics",
                                 "Late-arriving data and backfill pattern"],
            assumptions=["Incremental merge reads ~3x the changed data", "Slot-hour energy equivalence (factors.yaml: bigquery)"],
        ))
    return out


def bigquery_schedule(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["bigquery_schedule"], ctx.model
    out = []
    for name, g in ctx.table("bigquery_jobs").groupby("query_name"):
        runs_per_day = len(g) / max(1, ctx.period_days)
        unchanged = 1 - float(g.source_changed_since_last_run.mean())
        if runs_per_day < r["min_runs_per_day"] or unchanged < r["unchanged_run_share_min"]:
            continue
        keep = g[g.source_changed_since_last_run.astype(bool)]
        region = g.region.iloc[0]
        before = m.impact(m.bigquery_kwh(g.slot_ms.sum()), m.bigquery_cost(g.bytes_scanned_tib.sum()), region)
        after = m.impact(m.bigquery_kwh(keep.slot_ms.sum()), m.bigquery_cost(keep.bytes_scanned_tib.sum()), region)
        conf = _Confidence(0.80, "per-run source-change flag available")
        out.append(_opp(
            before, after, conf,
            detector="bigquery_schedule", action_class="event_trigger", technology="BigQuery", domain="digital", entity=name,
            title=f"Trigger {name} on source change instead of every hour",
            root_cause="unnecessary scheduling",
            proposed_action="Replace the fixed schedule with an event-driven trigger on source load completion "
                            "(or reduce cadence to the business freshness requirement).",
            capacity_effect=f"Runs {len(g)} -> {len(keep)} per period",
            effort="S",
            evidence=[
                Evidence("Runs per day", round(runs_per_day, 1), "runs/day", "observed", "bigquery_jobs"),
                Evidence("Runs with unchanged source", round(unchanged, 2), "share", "derived", "bigquery_jobs"),
                Evidence("Data scanned", round(float(g.bytes_scanned_tib.sum()), 1), "TiB", "observed", "bigquery_jobs"),
                Evidence("Dashboard freshness requirement", "unknown", "", "missing", ""),
            ],
            missing_information=["Business freshness requirement for dashboard consumers"],
            assumptions=["Runs on unchanged source produce identical results"],
        ))
    return out


def dataproc_idle(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["dataproc_idle"], ctx.model
    idle_util = m.f["compute"]["idle_utilisation"]
    out = []
    for name, g in ctx.table("dataproc_clusters").groupby("cluster"):
        prov, busy = float(g.provisioned_hours.sum()), float(g.busy_hours.sum())
        idle_ratio = 1 - busy / prov if prov else 0.0
        if idle_ratio < r["idle_ratio_min"]:
            continue
        node_v, node_m = g.nodes * g.vcpus_per_node, g.nodes * g.mem_gb_per_node
        idle_h = (g.provisioned_hours - g.busy_hours).clip(lower=0)
        new_prov = np.minimum(g.provisioned_hours, g.busy_hours + r["buffer_hours_per_day"])
        new_idle = (new_prov - g.busy_hours).clip(lower=0)
        busy_kwh = m.compute_kwh(g.busy_hours * node_v, g.busy_hours * node_m, g.busy_cpu_util).sum()
        region = g.region.iloc[0]
        before = m.impact(busy_kwh + m.compute_kwh(idle_h * node_v, idle_h * node_m, idle_util).sum(),
                          m.compute_cost(g.provisioned_hours * node_v, g.provisioned_hours * node_m).sum(), region)
        after = m.impact(busy_kwh + m.compute_kwh(new_idle * node_v, new_idle * node_m, idle_util).sum(),
                         m.compute_cost(new_prov * node_v, new_prov * node_m).sum(), region)
        conf = _Confidence(0.85, f"{len(g)} days of provisioned vs busy hours")
        conf.penalise(float(g.busy_hours.std() / max(g.busy_hours.mean(), 1e-6)) > 0.5, 0.1, "highly variable demand")
        out.append(_opp(
            before, after, conf,
            detector="dataproc_idle", action_class="ephemeral_cluster", technology="Dataproc", domain="digital", entity=name,
            title=f"Make Dataproc cluster {name} ephemeral (idle {_pct(idle_ratio)} of the time)",
            root_cause="idle capacity",
            proposed_action="Use job-scoped ephemeral clusters or Dataproc Serverless, or set an idle-delete TTL "
                            f"with a {r['buffer_hours_per_day']} h/day buffer; keep autoscaling for bursts.",
            capacity_effect=f"Provisioned hours {prov:.0f} -> {float(new_prov.sum()):.0f} per period",
            effort="M",
            evidence=[
                Evidence("Provisioned hours", round(prov, 1), "h", "observed", "dataproc_clusters"),
                Evidence("Busy hours", round(busy, 1), "h", "observed", "dataproc_clusters"),
                Evidence("Idle ratio", round(idle_ratio, 2), "share", "derived", ""),
                Evidence("Nodes x vCPU", f"{int(g.nodes.iloc[0])} x {int(g.vcpus_per_node.iloc[0])}", "", "observed", "dataproc_clusters"),
                Evidence("Start-up buffer", r["buffer_hours_per_day"], "h/day", "assumed", "rules.yaml"),
            ],
            missing_information=["Interactive users' tolerance for cluster start-up latency",
                                 "Jobs that depend on cluster-local state (HDFS, cached data)"],
            assumptions=["Idle nodes draw idle power only (factors.yaml: compute.idle_utilisation)"],
        ))
    return out


def gcs_lifecycle(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["gcs_lifecycle"], ctx.model
    hours, months = ctx.period_days * 24, ctx.period_days / DAYS_PER_MONTH
    out = []
    for row in ctx.table("gcs_buckets").itertuples(index=False):
        stale_share = row.stale_gb_90d / row.size_gb if row.size_gb else 0.0
        if row.size_gb < r["min_size_gb"] or stale_share < r["stale_share_min"] or bool(row.lifecycle_rule):
            continue
        before = m.impact(m.storage_kwh(row.size_gb, hours), m.storage_cost(row.size_gb, row.storage_class, months), row.region)
        base_evidence = [
            Evidence("Bucket size", row.size_gb, "GB", "observed", "gcs_buckets"),
            Evidence("Not accessed in 90 days", row.stale_gb_90d, "GB", "observed", "gcs_buckets"),
            Evidence("Stale share", round(stale_share, 2), "share", "derived", ""),
            Evidence("Storage class", row.storage_class, "", "observed", "gcs_buckets"),
            Evidence("Lifecycle rule present", bool(row.lifecycle_rule), "", "observed", "gcs_buckets"),
            Evidence("Access-log coverage", row.access_log_coverage, "share", "observed", "gcs_buckets"),
        ]
        common_missing = [f"Access logs cover only {_pct(row.access_log_coverage)} of objects"] if row.access_log_coverage < 1 else []

        if row.purpose in r["delete_purposes"]:
            deletable = row.stale_gb_90d * r["deletable_share_of_stale"]
            remain = row.size_gb - deletable
            after = m.impact(m.storage_kwh(remain, hours), m.storage_cost(remain, row.storage_class, months), row.region)
            conf = _Confidence(0.90, "bucket inventory with access logs")
            conf.penalise(row.access_log_coverage < 0.95, 0.10, "access-log coverage below 95%")
            out.append(_opp(
                before, after, conf,
                detector="gcs_lifecycle", action_class="lifecycle_delete", technology="GCS", domain="digital", entity=row.bucket,
                title=f"Add delete lifecycle rule to {row.bucket} ({row.purpose} data)",
                root_cause="storage retention",
                proposed_action=f"Add an age-based delete rule for {row.purpose} objects not accessed in 90 days "
                                "(soft-delete window retained).",
                capacity_effect=f"Stored data {row.size_gb / 1024:.0f} -> {remain / 1024:.0f} TB",
                effort="S",
                evidence=base_evidence + [Evidence("Deletable share of stale data", r["deletable_share_of_stale"], "share", "assumed", "rules.yaml")],
                missing_information=common_missing + ["Owner confirmation that no process re-reads old objects"],
                assumptions=["Storage energy per TB-hour and replication (factors.yaml: storage)"],
            ))

        if row.purpose not in r["delete_purposes"] or row.purpose == "logs":
            target = r["transition_target"].get(row.purpose, r["transition_target"]["default"])
            cur_price, new_price = m.storage_price(row.storage_class), m.storage_price(target)
            if new_price >= cur_price:
                continue
            after_cost = (m.storage_cost(row.size_gb - row.stale_gb_90d, row.storage_class, months)
                          + m.storage_cost(row.stale_gb_90d, target, months))
            after = m.impact(m.storage_kwh(row.size_gb, hours), after_cost, row.region)
            conf = _Confidence(0.85, "bucket inventory with access logs")
            conf.penalise(row.access_log_coverage < 0.95, 0.10, "access-log coverage below 95%")
            out.append(_opp(
                before, after, conf,
                detector="gcs_lifecycle", action_class="storage_class_transition", technology="GCS", domain="digital",
                entity=row.bucket, title=f"Transition stale objects in {row.bucket} to {target}",
                root_cause="storage retention",
                proposed_action=f"Add a lifecycle SetStorageClass rule moving objects not accessed in 90 days to {target}; "
                                "data is retained in full.",
                capacity_effect=f"{row.stale_gb_90d / 1024:.0f} TB moved to {target}; nothing deleted",
                effort="S",
                evidence=base_evidence + [Evidence(f"Price {row.storage_class} -> {target}", f"{cur_price} -> {new_price}",
                                                   "per GB-month", "assumed", "factors.yaml")],
                missing_information=common_missing + ["Expected retrieval frequency (retrieval fees and minimum storage duration)"],
                assumptions=["Colder classes assumed to use the same media energy, so only cost changes"],
            ))
    return out


def jenkins_builds(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["jenkins_builds"], ctx.model
    util = m.f["compute"]["ci_build_utilisation"]
    out = []
    for name, g in ctx.table("jenkins_builds").groupby("pipeline"):
        timer = g[g.trigger == "timer"]
        if timer.empty:
            continue
        unchanged = timer[~timer.code_changed.astype(bool)]
        share = len(unchanged) / len(timer)
        if share < r["unchanged_share_min"]:
            continue

        def imp(df):
            vh = (df.duration_min / 60 * df.executor_vcpus).sum()
            mh = (df.duration_min / 60 * df.executor_mem_gb).sum()
            return m.impact(m.compute_kwh(vh, mh, util), m.compute_cost(vh, mh), g.region.iloc[0])

        before, after = imp(g), imp(g.drop(unchanged.index))
        conf = _Confidence(0.85, "SCM change flag on every build")
        out.append(_opp(
            before, after, conf,
            detector="jenkins_builds", action_class="build_on_change", technology="Jenkins", domain="digital", entity=name,
            title=f"Build {name} on code change, not on a timer",
            root_cause="repeated builds",
            proposed_action="Switch timer triggers to SCM/webhook triggers, or skip the build when no relevant path changed "
                            "since the last successful build.",
            capacity_effect=f"Builds {len(g)} -> {len(g) - len(unchanged)} per period",
            effort="S",
            evidence=[
                Evidence("Timer-triggered builds", len(timer), "builds", "observed", "jenkins_builds"),
                Evidence("Timer builds with no code change", len(unchanged), "builds", "observed", "jenkins_builds"),
                Evidence("Share without change", round(share, 2), "share", "derived", ""),
                Evidence("Executor size", f"{int(g.executor_vcpus.iloc[0])} vCPU", "", "observed", "jenkins_builds"),
                Evidence("Executor utilisation during build", util, "ratio", "assumed", "factors.yaml"),
            ],
            missing_information=["Downstream jobs that rely on a nightly cadence (e.g. regression packs)",
                                 "Dependency or base-image updates that should still trigger a rebuild"],
            assumptions=["Executor power and price coefficients (factors.yaml: compute)"],
        ))
    return out


def jenkins_artifacts(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["jenkins_artifacts"], ctx.model
    hours, months = ctx.period_days * 24, ctx.period_days / DAYS_PER_MONTH
    builds = ctx.table("jenkins_builds")
    out = []
    for row in ctx.table("jenkins_artifacts").itertuples(index=False):
        if row.retained_artifacts <= r["max_retained_artifacts"]:
            continue
        gb_before = row.retained_artifacts * row.avg_artifact_gb
        gb_after = r["max_retained_artifacts"] * row.avg_artifact_gb
        region = builds.loc[builds.pipeline == row.pipeline, "region"].iloc[0] if not builds.empty else "default"
        before = m.impact(m.storage_kwh(gb_before, hours, "ssd"), m.disk_cost(gb_before, months), region)
        after = m.impact(m.storage_kwh(gb_after, hours, "ssd"), m.disk_cost(gb_after, months), region)
        conf = _Confidence(0.85, "artifact inventory")
        out.append(_opp(
            before, after, conf,
            detector="jenkins_artifacts", action_class="artifact_retention", technology="Jenkins", domain="digital",
            entity=row.pipeline, title=f"Apply artifact retention to {row.pipeline} (keep {r['max_retained_artifacts']})",
            root_cause="storage retention",
            proposed_action=f"Configure a build discarder keeping the last {r['max_retained_artifacts']} artifacts; "
                            "publish release artifacts to the artifact repository instead of the CI server.",
            capacity_effect=f"Artifact storage {gb_before:.0f} -> {gb_after:.0f} GB",
            effort="S",
            evidence=[
                Evidence("Retained artifacts", row.retained_artifacts, "artifacts", "observed", "jenkins_artifacts"),
                Evidence("Average artifact size", row.avg_artifact_gb, "GB", "observed", "jenkins_artifacts"),
                Evidence("Retention policy", row.retention_policy, "", "observed", "jenkins_artifacts"),
                Evidence("Artifact storage released", round(gb_before - gb_after, 0), "GB", "derived", ""),
                Evidence("Storage media", "SSD persistent disk", "", "assumed", "factors.yaml"),
            ],
            missing_information=["Audit or release-evidence retention requirements for CI artifacts"],
            assumptions=["Artifacts stored on SSD persistent disk (factors.yaml: storage)"],
        ))
    return out


def harness_deployments(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["harness_deployments"], ctx.model
    util = m.f["compute"]["deploy_utilisation"]
    df = ctx.table("harness_deployments")
    if df.empty:
        return []
    df = df.sort_values(["pipeline", "env", "deploy_ts"]).copy()
    df["redundant"] = df.artifact_digest == df.groupby(["pipeline", "env"])["artifact_digest"].shift(1)
    out = []
    for name, g in df.groupby("pipeline"):
        share = float(g.redundant.mean())
        if share < r["redundant_share_min"]:
            continue

        def imp(x):
            vh = (x.duration_min / 60 * x.vcpus).sum()
            return m.impact(m.compute_kwh(vh, vh * 4, util), m.compute_cost(vh, vh * 4), g.region.iloc[0])

        before, after = imp(g), imp(g[~g.redundant])
        envs = ", ".join(sorted(g.env.unique()))
        conf = _Confidence(0.80, "artifact digest recorded for every deployment")
        conf.penalise(True, 0.05, "configuration/secret changes not visible in telemetry")
        out.append(_opp(
            before, after, conf,
            detector="harness_deployments", action_class="skip_redundant_deploy", technology="Harness", domain="digital",
            entity=name, title=f"Skip redundant deployments in {name}",
            root_cause="repeated deployments",
            proposed_action="Trigger deployments on new artifact or config version; add a pipeline condition that skips "
                            "when artifact digest and config hash match the running version.",
            capacity_effect=f"Deployments {len(g)} -> {int((~g.redundant).sum())} per period across {envs}",
            effort="S",
            evidence=[
                Evidence("Deployments", len(g), "deploys", "observed", "harness_deployments"),
                Evidence("Same digest as previous deploy (same env)", int(g.redundant.sum()), "deploys", "derived", "harness_deployments"),
                Evidence("Redundant share", round(share, 2), "share", "derived", ""),
                Evidence("Trigger type", ", ".join(sorted(g.trigger.unique())), "", "observed", "harness_deployments"),
                Evidence("Config / secret version per deploy", "not captured", "", "missing", ""),
            ],
            missing_information=["Config or secret changes deployed alongside the same artifact",
                                 "Whether scheduled redeploys are used as an environment-reset mechanism"],
            assumptions=["Delegate/test stage sizing and 4 GB per vCPU (normalise.py)"],
        ))
    return out


def kubernetes_offhours(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["kubernetes_offhours"], ctx.model
    start, end = r["business_hours"]
    out = []
    for name, g in ctx.table("kubernetes_nodepools").groupby("cluster"):
        ts = pd.to_datetime(g.ts)
        business = ts.dt.dayofweek.isin(r["business_weekdays"]) & (ts.dt.hour >= start) & (ts.dt.hour < end)
        off = g[~business]
        if off.empty:
            continue
        off_util, biz_util = float(off.cpu_util.mean()), float(g[business].cpu_util.mean())
        if off_util > r["offhours_util_max"]:
            continue
        saved_nodes = (off.nodes - r["min_nodes_offhours"]).clip(lower=0)
        saved_v, saved_m = (saved_nodes * off.vcpus_per_node).sum(), (saved_nodes * off.mem_gb_per_node).sum()
        region = g.region.iloc[0]
        vh, mh = g.nodes * g.vcpus_per_node, g.nodes * g.mem_gb_per_node
        before = m.impact(m.compute_kwh(vh, mh, g.cpu_util).sum(), m.compute_cost(vh, mh).sum(), region)
        after = m.impact(before["energy_kwh"] - float(m.compute_kwh(saved_v, saved_m, 0.0)),
                         before["cost"] - float(m.compute_cost(saved_v, saved_m)), region)
        asset = ctx.asset(name)
        conf = _Confidence(0.85, "hourly node and utilisation telemetry")
        conf.penalise(biz_util < r["offhours_util_max"], 0.05, "low utilisation in business hours too: purpose unclear")
        out.append(_opp(
            before, after, conf,
            detector="kubernetes_offhours", action_class="schedule_off", technology="Kubernetes", domain="digital", entity=name,
            title=f"Scale {name} down to {r['min_nodes_offhours']} nodes outside business hours",
            root_cause="idle capacity / unnecessary scheduling",
            proposed_action="Schedule node-pool scale-down (and workload scale-to-zero) outside business hours, "
                            "with self-service override for out-of-hours testing.",
            capacity_effect=f"Off-hours nodes {int(off.nodes.max())} -> {r['min_nodes_offhours']}; business hours unchanged",
            effort="S",
            evidence=[
                Evidence("Environment", asset.get("env", "unknown"), "", "observed", "asset register"),
                Evidence("Off-hours share of node-hours", round(off.nodes.sum() / g.nodes.sum(), 2), "share", "derived", ""),
                Evidence("Off-hours mean CPU", round(off_util, 3), "ratio", "observed", "kubernetes_nodepools"),
                Evidence("Business-hours mean CPU", round(biz_util, 3), "ratio", "observed", "kubernetes_nodepools"),
                Evidence("Nodes", int(g.nodes.max()), "nodes", "observed", "kubernetes_nodepools"),
                Evidence("Business hours", f"{start}:00-{end}:00 Mon-Fri", "", "assumed", "rules.yaml"),
            ],
            missing_information=["Overnight batch or test schedules that run in this cluster",
                                 "Teams working outside the assumed business hours"],
            assumptions=["Freed nodes save idle power and memory only (conservative)"],
        ))
    return out


# =================================================================================================
# Physical detectors
# =================================================================================================
def facilities_occupancy(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["facilities_occupancy"], ctx.model
    fac = m.f["facilities"]
    out = []
    for floor, g in ctx.table("facilities_daily").groupby("floor"):
        weekday = pd.to_datetime(g.date).dt.dayofweek < 5
        occ_rate = g.occupied_desks / g.capacity_desks
        occ_wd, occ_all = float(occ_rate[weekday].mean()), float(occ_rate.mean())
        if g.schedule.iloc[0] != "fixed_full_capacity" or occ_wd > r["occupancy_max"]:
            continue
        gaps = int(g.hvac_kwh.isna().sum() + g.lighting_kwh.isna().sum())
        energy = float((g.hvac_kwh.fillna(g.hvac_kwh.median()) + g.lighting_kwh.fillna(g.lighting_kwh.median())).sum())
        price = fac["price_per_kwh"]
        before = m.impact(energy, energy * price, "uk")
        evidence = [
            Evidence("Weekday occupancy", round(occ_wd, 2), "share", "observed", "facilities_daily (badge data)"),
            Evidence("HVAC + lighting energy", round(energy, 0), "kWh", "observed" if gaps == 0 else "derived", "BMS sub-meters"),
            Evidence("Schedule", g.schedule.iloc[0], "", "observed", "BMS"),
            Evidence("Meter gaps", gaps, "days", "missing" if gaps else "observed", "facilities_daily"),
        ]
        frac = fac["hvac_occupancy_responsiveness"] * (1 - occ_all)
        after = m.impact(energy * (1 - frac), energy * (1 - frac) * price, "uk")
        conf = _Confidence(0.75, "daily sub-metered energy and occupancy")
        conf.penalise(gaps > 0, 0.10, f"{gaps} days of meter gaps filled with median")
        out.append(_opp(
            before, after, conf,
            detector="facilities_occupancy", action_class="occupancy_hvac", technology="Office energy", domain="physical",
            entity=floor, title=f"Link HVAC and lighting on {floor} to occupancy",
            root_cause="occupancy",
            proposed_action="Move the BMS from a fixed full-capacity schedule to occupancy-linked setpoints and lighting "
                            "zones, with reduced weekend operation.",
            capacity_effect="Floor stays open; comfort setpoints maintained in occupied zones",
            effort="M",
            evidence=evidence + [Evidence("Occupancy-responsive share of energy", fac["hvac_occupancy_responsiveness"],
                                          "share", "assumed", "factors.yaml")],
            missing_information=["BMS zoning granularity and minimum ventilation requirements",
                                 "Occupancy sensor coverage (badge data used as a proxy)"],
            assumptions=["Share of HVAC + lighting energy that tracks occupancy (factors.yaml)"],
        ))
        if occ_wd <= r["consolidation_occupancy_max"]:
            frac = fac["consolidation_saving_fraction"]
            after = m.impact(energy * (1 - frac), energy * (1 - frac) * price, "uk")
            conf = _Confidence(0.60, "occupancy well below consolidation threshold")
            conf.penalise(True, 0.05, "demand from teams on other floors not modelled")
            out.append(_opp(
                before, after, conf,
                detector="facilities_occupancy", action_class="consolidate_floor", technology="Office energy",
                domain="physical", entity=floor, title=f"Consolidate {floor} into other floors",
                root_cause="occupancy",
                proposed_action="Relocate the floor's users to under-used capacity elsewhere and set the floor to "
                                "set-back mode.",
                capacity_effect=f"{int(g.capacity_desks.iloc[0])} desks withdrawn",
                effort="L",
                evidence=evidence + [Evidence("Energy avoided if closed", frac, "share", "assumed", "factors.yaml")],
                missing_information=["Desk demand on receiving floors at peak days",
                                     "Location of accessibility, first-aid and evacuation facilities"],
                assumptions=["Share of a floor's energy avoided in set-back mode (factors.yaml)"],
            ))
    return out


def travel_mode_shift(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["travel_mode_shift"], ctx.model
    t = m.f["travel"]
    out = []
    for route, g in ctx.table("travel_trips").groupby("route"):
        flights = g[g["mode"] == "flight_domestic"]
        one_way = float(g.one_way_km.iloc[0])
        if route not in r["rail_feasible_routes"] or flights.empty or one_way > r["max_rail_distance_km"]:
            continue
        pkm = float((flights.distance_km * flights.travellers).sum())
        adopt = r["adoption_share"]
        kf, kr = t["kg_per_passenger_km"]["flight_domestic"], t["kg_per_passenger_km"]["rail"]
        flight_cost = float(flights.cost.sum())
        before = m.impact(0.0, flight_cost, "uk", extra_co2e=pkm * kf)
        after = m.impact(0.0, flight_cost * (1 - adopt) + pkm * adopt * t["cost_per_passenger_km"]["rail"], "uk",
                         extra_co2e=pkm * (1 - adopt) * kf + pkm * adopt * kr)
        conf = _Confidence(0.70, "trip-level booking data")
        conf.penalise(True, 0.05, "journey-time and accessibility needs per trip unknown")
        out.append(_opp(
            before, after, conf,
            detector="travel_mode_shift", action_class="mode_shift", technology="Business travel", domain="physical",
            entity=route, title=f"Rail-first policy for {route}",
            root_cause="behaviour",
            proposed_action=(f"Make rail the default booking for {route} with exceptions for accessibility, urgency or "
                             f"connecting travel; target {adopt:.0%} adoption."),
            capacity_effect="No change in trips; mode changes for eligible journeys",
            effort="M",
            evidence=[
                Evidence("Flights on route", len(flights), "trips", "observed", "travel_trips"),
                Evidence("One-way distance", one_way, "km", "observed", "travel_trips"),
                Evidence("Flight passenger-km", round(pkm, 0), "pkm", "observed", "travel_trips"),
                Evidence("Emission factor flight / rail", f"{kf} / {kr}", "kgCO2e/pkm", "assumed", "factors.yaml"),
                Evidence("Adoption share", adopt, "share", "assumed", "rules.yaml"),
            ],
            missing_information=["Journey-time impact and exceptions (accessibility, caring duties, urgency)"],
            assumptions=["Aggregated by route; no individual traveller is assessed"],
        ))
    return out


def print_efficiency(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["print_efficiency"], ctx.model
    p = m.f["print"]
    out = []
    for row in ctx.table("print_volumes").itertuples(index=False):
        low_duplex = row.duplex_share < r["duplex_share_min"]
        high_uncollected = row.uncollected_share > r["uncollected_share_max"]
        if not (low_duplex or high_uncollected):
            continue
        saved = 0.0
        if low_duplex:
            saved += row.pages_printed * (1 - row.duplex_share) * p["duplex_page_reduction"]
        if high_uncollected:
            saved += row.pages_printed * row.uncollected_share * p["uncollected_reduction"]
        pages_after = row.pages_printed - saved
        before = m.impact(0.0, row.pages_printed * p["cost_per_page"], "uk", row.pages_printed * p["kg_per_page"])
        after = m.impact(0.0, pages_after * p["cost_per_page"], "uk", pages_after * p["kg_per_page"])
        conf = _Confidence(0.75, "print-server logs")
        out.append(_opp(
            before, after, conf,
            detector="print_efficiency", action_class="print_defaults", technology="Print", domain="physical",
            entity=row.site, title=f"Duplex-by-default and pull printing at {row.site}",
            root_cause="behaviour",
            proposed_action="Set duplex and mono as print defaults and release jobs at the device (pull printing).",
            capacity_effect=f"Pages {row.pages_printed:,.0f} -> {pages_after:,.0f} per period",
            effort="S",
            evidence=[
                Evidence("Pages printed", row.pages_printed, "pages", "observed", "print_volumes"),
                Evidence("Duplex share", row.duplex_share, "share", "observed", "print_volumes"),
                Evidence("Uncollected job share", row.uncollected_share, "share", "observed", "print_volumes"),
                Evidence("Page reduction factors", f"{p['duplex_page_reduction']} / {p['uncollected_reduction']}", "", "assumed", "factors.yaml"),
            ],
            missing_information=["Documents that must be single-sided (regulatory or customer forms)"],
            assumptions=["Lifecycle CO2e and cost per page (factors.yaml: print)"],
        ))
    return out


def waste_segregation(ctx: DetectorContext) -> list[Opportunity]:
    r, m = ctx.rules["waste_segregation"], ctx.model
    w = m.f["waste"]
    out = []
    for row in ctx.table("waste_records").itertuples(index=False):
        total = row.general_waste_kg + row.recycled_kg
        rate = row.recycled_kg / total if total else 0.0
        if rate >= r["recycling_rate_min"]:
            continue
        shift = (r["achievable_recycling_rate"] - rate) * total

        def imp(general, recycled):
            co2 = general * w["kg_co2e_per_kg_general"] + recycled * w["kg_co2e_per_kg_recycled"]
            cost = general * w["cost_per_kg_general"] + recycled * w["cost_per_kg_recycled"]
            return m.impact(0.0, cost, "uk", co2)

        before = imp(row.general_waste_kg, row.recycled_kg)
        after = imp(row.general_waste_kg - shift, row.recycled_kg + shift)
        conf = _Confidence(0.65, "monthly waste-contractor weights")
        conf.penalise(True, 0.05, "waste composition audit not available")
        out.append(_opp(
            before, after, conf,
            detector="waste_segregation", action_class="waste_segregation", technology="Waste", domain="physical",
            entity=row.site, title=f"Improve waste segregation at {row.site}",
            root_cause="behaviour",
            proposed_action="Replace desk bins with central segregated stations and add clear signage; "
                            f"target a {r['achievable_recycling_rate']:.0%} recycling rate.",
            capacity_effect=f"{shift:,.0f} kg per period moved from general waste to recycling",
            effort="M",
            evidence=[
                Evidence("General waste", row.general_waste_kg, "kg", "observed", "waste_records"),
                Evidence("Recycled", row.recycled_kg, "kg", "observed", "waste_records"),
                Evidence("Recycling rate", round(rate, 2), "share", "derived", ""),
                Evidence("Achievable rate", r["achievable_recycling_rate"], "share", "assumed", "rules.yaml"),
            ],
            missing_information=["Waste composition audit (how much general waste is recyclable)"],
            assumptions=["Treatment emission and cost factors (factors.yaml: waste)"],
        ))
    return out


DETECTORS: tuple[Callable[[DetectorContext], list[Opportunity]], ...] = (
    dataflow_rightsizing,
    region_shift,
    bigquery_scans,
    bigquery_schedule,
    dataproc_idle,
    gcs_lifecycle,
    jenkins_builds,
    jenkins_artifacts,
    harness_deployments,
    kubernetes_offhours,
    facilities_occupancy,
    travel_mode_shift,
    print_efficiency,
    waste_segregation,
)


def run_detectors(ctx: DetectorContext) -> tuple[list[Opportunity], list[str]]:
    """Run every detector; a failing detector is reported, not fatal."""
    opportunities: list[Opportunity] = []
    issues: list[str] = []
    for detector in DETECTORS:
        try:
            opportunities.extend(detector(ctx))
        except KeyError as exc:  # missing table/column/rule
            issues.append(f"Detector '{detector.__name__}' skipped: missing {exc}.")
    return opportunities, issues
