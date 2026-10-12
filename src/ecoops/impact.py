"""Energy, carbon and cost estimation. Every coefficient comes from factors.yaml."""

from __future__ import annotations

from typing import Any

import numpy as np

from .models import IMPACT_KEYS

HOURS_PER_MONTH = 730.0
DAYS_PER_MONTH = 30.4375


class ImpactModel:
    def __init__(self, factors: dict[str, Any]):
        self.f = factors

    # --- compute -------------------------------------------------------------------------------
    def watts_per_vcpu(self, util):
        c = self.f["compute"]
        u = np.clip(util, 0.0, 1.0)
        return c["min_watts_per_vcpu"] + u * (c["max_watts_per_vcpu"] - c["min_watts_per_vcpu"])

    def compute_kwh(self, vcpu_hours, mem_gb_hours, util):
        c = self.f["compute"]
        return (
            vcpu_hours * self.watts_per_vcpu(util) / 1000.0
            + mem_gb_hours * c["memory_kwh_per_gb_hour"]
        ) * c["pue"]

    def compute_cost(self, vcpu_hours, mem_gb_hours):
        c = self.f["compute"]
        return vcpu_hours * c["price_per_vcpu_hour"] + mem_gb_hours * c["price_per_gb_mem_hour"]

    # --- BigQuery ------------------------------------------------------------------------------
    def bigquery_kwh(self, slot_ms):
        b = self.f["bigquery"]
        slot_hours = slot_ms / 3.6e6
        return self.compute_kwh(slot_hours * b["slot_hour_vcpu_equivalent"], 0.0, b["slot_utilisation"])

    def bigquery_cost(self, tib_scanned):
        return tib_scanned * self.f["bigquery"]["price_per_tib_scanned"]

    # --- storage -------------------------------------------------------------------------------
    def storage_kwh(self, gb, hours, media: str = "hdd"):
        s = self.f["storage"]
        coef = s["ssd_wh_per_tb_hour"] if media == "ssd" else s["hdd_wh_per_tb_hour"]
        return gb / 1024.0 * hours * coef * s["replication_factor"] / 1000.0 * self.f["compute"]["pue"]

    def storage_price(self, storage_class: str) -> float:
        prices = self.f["storage"]["price_per_gb_month"]
        return prices.get(storage_class, prices["STANDARD"])

    def storage_cost(self, gb, storage_class: str, months):
        return gb * self.storage_price(storage_class) * months

    def disk_cost(self, gb, months):
        return gb * self.f["storage"]["persistent_disk_price_per_gb_month"] * months

    # --- carbon --------------------------------------------------------------------------------
    def grid_intensity(self, region: str) -> float:
        if region in ("uk", "office"):
            return float(self.f["facilities"]["grid_intensity_kg_per_kwh"])
        grid = self.f["grid_intensity_kg_per_kwh"]
        return float(grid.get(region, grid["default"]))

    def impact(self, kwh, cost, region: str, extra_co2e: float = 0.0) -> dict[str, float]:
        kwh = float(kwh)
        return {
            "energy_kwh": kwh,
            "co2e_kg": kwh * self.grid_intensity(region) + float(extra_co2e),
            "cost": float(cost),
        }

    def annual_factor(self, period_days: int) -> float:
        return self.f["meta"]["annualisation_days"] / max(1, period_days)


def diff(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    return {k: float(before.get(k, 0.0) - after.get(k, 0.0)) for k in IMPACT_KEYS}


def scale(values: dict[str, float], factor: float) -> dict[str, float]:
    return {k: float(values.get(k, 0.0) * factor) for k in IMPACT_KEYS}
