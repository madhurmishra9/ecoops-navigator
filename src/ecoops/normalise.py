"""Normalisation: turn heterogeneous telemetry into comparable, provenance-tagged measures.

Output 1 — ``measures``: long format, one row per (source, entity, metric) with
period, unit, provenance (observed | derived | assumed | missing), confidence and note.

Output 2 — ``footprint``: one row per entity with period and annualised energy,
CO2e and cost. This is the "current state" baseline for the leadership view.
"""

from __future__ import annotations

import pandas as pd

from .impact import DAYS_PER_MONTH, ImpactModel
from .models import IMPACT_KEYS


def completeness(df: pd.DataFrame, columns: list[str]) -> float:
    cols = [c for c in columns if c in df.columns]
    if not cols or df.empty:
        return 0.0
    return float(df[cols].notna().mean().mean())


class _Collector:
    def __init__(self, model: ImpactModel, period_start, period_end, currency: str):
        self.model = model
        self.period_start = period_start
        self.period_end = period_end
        self.currency = currency
        self.rows: list[dict] = []
        self.fp: list[dict] = []

    def add(self, source, technology, domain, entity, metric, value, unit, provenance, confidence, note=""):
        self.rows.append(
            dict(source=source, technology=technology, domain=domain, entity=entity,
                 period_start=self.period_start, period_end=self.period_end, metric=metric,
                 value=float(value), unit=unit, provenance=provenance,
                 confidence=round(float(confidence), 2), note=note)
        )

    def footprint(self, source, technology, domain, entity, region, kwh, cost, confidence,
                  extra_co2e=0.0, energy_provenance="derived", energy_note="", co2e_note=""):
        imp = self.model.impact(kwh, cost, region, extra_co2e)
        intensity = self.model.grid_intensity(region)
        self.add(source, technology, domain, entity, "energy_kwh", imp["energy_kwh"], "kWh", energy_provenance,
                 confidence, energy_note or "Estimated from configuration x utilisation x assumed power coefficients")
        self.add(source, technology, domain, entity, "co2e_kg", imp["co2e_kg"], "kgCO2e", "derived",
                 confidence * 0.9, co2e_note or f"Energy x grid intensity {intensity} kgCO2e/kWh (assumed, region {region})")
        self.add(source, technology, domain, entity, "cost", imp["cost"], self.currency, "derived",
                 confidence, "Illustrative list prices (assumed)")
        self.fp.append(dict(source=source, technology=technology, domain=domain, entity=entity, region=region,
                            confidence=round(float(confidence), 2), **imp))


# --- digital ------------------------------------------------------------------------------------
def _dataflow(c: _Collector, df: pd.DataFrame) -> None:
    m = c.model
    df = df.copy()
    df["vcpu_hours"] = df.workers * df.vcpus_per_worker * df.runtime_min / 60
    df["mem_gb_hours"] = df.workers * df.mem_gb_per_worker * df.runtime_min / 60
    util = df.cpu_util_avg.fillna(df.cpu_util_avg.median())
    df["kwh"] = m.compute_kwh(df.vcpu_hours, df.mem_gb_hours, util)
    df["cost"] = m.compute_cost(df.vcpu_hours, df.mem_gb_hours)
    for name, g in df.groupby("job_name"):
        comp = completeness(g, ["runtime_min", "cpu_util_p95", "mem_util_p95"])
        base = ("dataflow_jobs", "Dataflow", "digital", name)
        c.add(*base, "executions", len(g), "runs", "observed", comp)
        c.add(*base, "runtime_hours", g.runtime_min.sum() / 60, "h", "observed", comp)
        c.add(*base, "vcpu_hours", g.vcpu_hours.sum(), "vCPU-h", "derived", 0.9, "workers x vCPU per worker x runtime")
        c.add(*base, "cpu_util_p95_median", g.cpu_util_p95.median(), "ratio", "observed", comp)
        c.add(*base, "mem_util_p95_median", g.mem_util_p95.median(), "ratio", "observed", comp)
        c.footprint(*base, g.region.iloc[0], g.kwh.sum(), g.cost.sum(), 0.6 * comp)


def _bigquery(c: _Collector, df: pd.DataFrame) -> None:
    m = c.model
    for name, g in df.groupby("query_name"):
        comp = completeness(g, ["bytes_scanned_tib", "slot_ms"])
        base = ("bigquery_jobs", "BigQuery", "digital", name)
        c.add(*base, "executions", len(g), "runs", "observed", comp)
        c.add(*base, "bytes_scanned_tib", g.bytes_scanned_tib.sum(), "TiB", "observed", comp)
        c.add(*base, "source_bytes_changed_tib", g.source_bytes_changed_tib.sum(), "TiB", "observed", comp)
        c.add(*base, "slot_hours", g.slot_ms.sum() / 3.6e6, "slot-h", "observed", comp)
        c.footprint(*base, g.region.iloc[0], m.bigquery_kwh(g.slot_ms.sum()), m.bigquery_cost(g.bytes_scanned_tib.sum()),
                    0.55 * comp, energy_note="Slot-hours x assumed vCPU equivalence and power coefficients")


def _dataproc(c: _Collector, df: pd.DataFrame, idle_util: float) -> None:
    m = c.model
    for name, g in df.groupby("cluster"):
        comp = completeness(g, ["provisioned_hours", "busy_hours"])
        node_v = g.nodes * g.vcpus_per_node
        node_m = g.nodes * g.mem_gb_per_node
        idle_h = (g.provisioned_hours - g.busy_hours).clip(lower=0)
        kwh = (m.compute_kwh(g.busy_hours * node_v, g.busy_hours * node_m, g.busy_cpu_util)
               + m.compute_kwh(idle_h * node_v, idle_h * node_m, idle_util)).sum()
        cost = m.compute_cost(g.provisioned_hours * node_v, g.provisioned_hours * node_m).sum()
        base = ("dataproc_clusters", "Dataproc", "digital", name)
        c.add(*base, "provisioned_hours", g.provisioned_hours.sum(), "h", "observed", comp)
        c.add(*base, "busy_hours", g.busy_hours.sum(), "h", "observed", comp)
        c.add(*base, "idle_ratio", 1 - g.busy_hours.sum() / g.provisioned_hours.sum(), "ratio", "derived", comp)
        c.footprint(*base, g.region.iloc[0], kwh, cost, 0.6 * comp)


def _gcs(c: _Collector, df: pd.DataFrame, period_days: int) -> None:
    m = c.model
    hours = period_days * 24
    months = period_days / DAYS_PER_MONTH
    for row in df.itertuples(index=False):
        base = ("gcs_buckets", "GCS", "digital", row.bucket)
        c.add(*base, "size_gb", row.size_gb, "GB", "observed", 1.0)
        c.add(*base, "stale_gb_90d", row.stale_gb_90d, "GB", "observed", row.access_log_coverage,
              "Not accessed in 90 days (access-log coverage below 100%)")
        c.add(*base, "stale_share", row.stale_gb_90d / row.size_gb if row.size_gb else 0.0, "ratio", "derived",
              row.access_log_coverage)
        c.footprint(*base, row.region, m.storage_kwh(row.size_gb, hours), m.storage_cost(row.size_gb, row.storage_class, months),
                    0.55, energy_note="Stored GB x assumed Wh/TB-h x replication")


def _jenkins(c: _Collector, builds: pd.DataFrame, artifacts: pd.DataFrame, util: float, period_days: int) -> None:
    m = c.model
    hours = period_days * 24
    months = period_days / DAYS_PER_MONTH
    art = artifacts.set_index("pipeline") if not artifacts.empty else pd.DataFrame()
    for name, g in builds.groupby("pipeline"):
        vcpu_h = (g.duration_min / 60 * g.executor_vcpus).sum()
        mem_h = (g.duration_min / 60 * g.executor_mem_gb).sum()
        kwh = m.compute_kwh(vcpu_h, mem_h, util)
        cost = m.compute_cost(vcpu_h, mem_h)
        base = ("jenkins_builds", "Jenkins", "digital", name)
        timer = g[g.trigger == "timer"]
        c.add(*base, "executions", len(g), "builds", "observed", 1.0)
        c.add(*base, "timer_builds_without_change", int((~timer.code_changed).sum()), "builds", "observed", 1.0)
        c.add(*base, "executor_vcpu_hours", vcpu_h, "vCPU-h", "derived", 0.9)
        if name in art.index:
            a = art.loc[name]
            gb = float(a.retained_artifacts * a.avg_artifact_gb)
            kwh += m.storage_kwh(gb, hours, "ssd")
            cost += m.disk_cost(gb, months)
            c.add(*base, "retained_artifacts", a.retained_artifacts, "artifacts", "observed", 1.0)
            c.add(*base, "artifact_storage_gb", gb, "GB", "derived", 0.9)
        c.footprint(*base, g.region.iloc[0], kwh, cost, 0.6)


def _harness(c: _Collector, df: pd.DataFrame, util: float) -> None:
    m = c.model
    df = df.sort_values(["pipeline", "env", "deploy_ts"]).copy()
    df["prev_digest"] = df.groupby(["pipeline", "env"])["artifact_digest"].shift(1)
    for name, g in df.groupby("pipeline"):
        vcpu_h = (g.duration_min / 60 * g.vcpus).sum()
        mem_h = vcpu_h * 4  # assumed 4 GB per vCPU for delegates/test runners
        base = ("harness_deployments", "Harness", "digital", name)
        c.add(*base, "deployments", len(g), "deploys", "observed", 1.0)
        c.add(*base, "redundant_deployments", int((g.artifact_digest == g.prev_digest).sum()), "deploys", "derived", 0.9,
              "Same artifact digest as the previous deploy to the same environment")
        c.footprint(*base, g.region.iloc[0], m.compute_kwh(vcpu_h, mem_h, util), m.compute_cost(vcpu_h, mem_h), 0.55)


def _kubernetes(c: _Collector, df: pd.DataFrame) -> None:
    m = c.model
    for name, g in df.groupby("cluster"):
        vcpu_h = g.nodes * g.vcpus_per_node
        mem_h = g.nodes * g.mem_gb_per_node
        base = ("kubernetes_nodepools", "Kubernetes", "digital", name)
        comp = completeness(g, ["nodes", "cpu_util"])
        c.add(*base, "node_hours", g.nodes.sum(), "node-h", "observed", comp)
        c.add(*base, "cpu_util_mean", g.cpu_util.mean(), "ratio", "observed", comp)
        c.footprint(*base, g.region.iloc[0], m.compute_kwh(vcpu_h, mem_h, g.cpu_util).sum(),
                    m.compute_cost(vcpu_h, mem_h).sum(), 0.6 * comp)


# --- physical -----------------------------------------------------------------------------------
def _facilities(c: _Collector, df: pd.DataFrame) -> None:
    price = c.model.f["facilities"]["price_per_kwh"]
    for floor, g in df.groupby("floor"):
        comp = completeness(g, ["hvac_kwh", "lighting_kwh", "occupied_desks"])
        weekday = pd.to_datetime(g.date).dt.dayofweek < 5
        occ = (g.occupied_desks / g.capacity_desks)[weekday].mean()
        hvac = g.hvac_kwh.fillna(g.hvac_kwh.median())
        light = g.lighting_kwh.fillna(g.lighting_kwh.median())
        kwh = float((hvac + light).sum())
        base = ("facilities_daily", "Office energy", "physical", floor)
        c.add(*base, "weekday_occupancy_rate", occ, "ratio", "observed", comp, "Badge / desk-booking data as occupancy proxy")
        c.add(*base, "hvac_kwh", hvac.sum(), "kWh", "observed" if comp == 1 else "derived", comp,
              "" if comp == 1 else "Meter gaps filled with floor median")
        c.add(*base, "lighting_kwh", light.sum(), "kWh", "observed", comp)
        c.footprint(*base, "uk", kwh, kwh * price, comp, energy_provenance="observed",
                    energy_note="Sub-metered HVAC + lighting")


def _travel(c: _Collector, df: pd.DataFrame) -> None:
    f = c.model.f["travel"]["kg_per_passenger_km"]
    for route, g in df.groupby("route"):
        pkm = g.distance_km * g.travellers
        co2 = float((pkm * g["mode"].map(f).fillna(f.get("car", 0.17))).sum())
        base = ("travel_trips", "Business travel", "physical", route)
        for mode, gm in g.groupby("mode"):
            c.add(*base, f"passenger_km_{mode}", (gm.distance_km * gm.travellers).sum(), "pkm", "observed", 1.0)
        c.footprint(*base, "uk", 0.0, g.cost.sum(), 0.75, extra_co2e=co2,
                    energy_note="Not electricity — emissions from passenger-km factors",
                    co2e_note="Passenger-km x mode factor (assumed)")


def _print(c: _Collector, df: pd.DataFrame) -> None:
    p = c.model.f["print"]
    for row in df.itertuples(index=False):
        base = ("print_volumes", "Print", "physical", row.site)
        c.add(*base, "pages_printed", row.pages_printed, "pages", "observed", 1.0)
        c.add(*base, "duplex_share", row.duplex_share, "ratio", "observed", 1.0)
        c.footprint(*base, "uk", 0.0, row.pages_printed * p["cost_per_page"], 0.6,
                    extra_co2e=row.pages_printed * p["kg_per_page"], energy_note="Not separately metered",
                    co2e_note="Pages x lifecycle factor per page (assumed)")


def _waste(c: _Collector, df: pd.DataFrame) -> None:
    w = c.model.f["waste"]
    for row in df.itertuples(index=False):
        total = row.general_waste_kg + row.recycled_kg
        base = ("waste_records", "Waste", "physical", row.site)
        c.add(*base, "general_waste_kg", row.general_waste_kg, "kg", "observed", 1.0)
        c.add(*base, "recycled_kg", row.recycled_kg, "kg", "observed", 1.0)
        c.add(*base, "recycling_rate", row.recycled_kg / total if total else 0.0, "ratio", "derived", 1.0)
        co2 = row.general_waste_kg * w["kg_co2e_per_kg_general"] + row.recycled_kg * w["kg_co2e_per_kg_recycled"]
        cost = row.general_waste_kg * w["cost_per_kg_general"] + row.recycled_kg * w["cost_per_kg_recycled"]
        c.footprint(*base, "uk", 0.0, cost, 0.65, extra_co2e=co2, energy_note="Not applicable",
                    co2e_note="Waste kg x treatment factor (assumed)")


def normalise(data: dict[str, pd.DataFrame], model: ImpactModel, period_start, period_end, period_days: int,
              currency: str = "GBP") -> tuple[pd.DataFrame, pd.DataFrame]:
    c = _Collector(model, period_start, period_end, currency)
    comp = model.f["compute"]

    def has(name: str) -> bool:
        return name in data and not data[name].empty

    if has("dataflow_jobs"):
        _dataflow(c, data["dataflow_jobs"])
    if has("bigquery_jobs"):
        _bigquery(c, data["bigquery_jobs"])
    if has("dataproc_clusters"):
        _dataproc(c, data["dataproc_clusters"], comp["idle_utilisation"])
    if has("gcs_buckets"):
        _gcs(c, data["gcs_buckets"], period_days)
    if has("jenkins_builds"):
        _jenkins(c, data["jenkins_builds"], data.get("jenkins_artifacts", pd.DataFrame()), comp["ci_build_utilisation"], period_days)
    if has("harness_deployments"):
        _harness(c, data["harness_deployments"], comp["deploy_utilisation"])
    if has("kubernetes_nodepools"):
        _kubernetes(c, data["kubernetes_nodepools"])
    if has("facilities_daily"):
        _facilities(c, data["facilities_daily"])
    if has("travel_trips"):
        _travel(c, data["travel_trips"])
    if has("print_volumes"):
        _print(c, data["print_volumes"])
    if has("waste_records"):
        _waste(c, data["waste_records"])

    measures = pd.DataFrame(c.rows)
    footprint = pd.DataFrame(c.fp)
    factor = model.annual_factor(period_days)
    for key in IMPACT_KEYS:
        footprint[f"annual_{key}"] = footprint[key] * factor
    return measures, footprint
