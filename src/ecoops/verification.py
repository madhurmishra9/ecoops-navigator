"""Post-change verification (stretch goal): compare realised outcomes with the original estimate.

With synthetic data, "realised" telemetry comes from ``generator.generate(applied=...)``.
With real data, pass a post-change dataset to ``compare`` instead.
"""

from __future__ import annotations

import pandas as pd

from .generator import SIMULATABLE, generate
from .models import IMPACT_KEYS
from .pipeline import AnalysisResult, run
from .settings import Settings, load_settings


def compare(before: AnalysisResult, after: AnalysisResult, opp_ids: list[str]) -> pd.DataFrame:
    """Per-entity comparison of estimated vs realised annual savings."""
    fb = before.footprint.set_index("entity")
    fa = after.footprint.set_index("entity")
    by_entity: dict[str, list] = {}
    for oid in opp_ids:
        o = before.get(oid)
        if o is None:
            continue
        by_entity.setdefault(o.entity, []).append(o)
    rows = []
    for entity, opps in by_entity.items():
        row = {"entity": entity, "actions": ", ".join(o.id for o in opps), "technology": opps[0].technology}
        for k in IMPACT_KEYS:
            est = sum(o.annual_savings.get(k, 0.0) for o in opps)
            realised = float(fb.loc[entity, f"annual_{k}"] - fa.loc[entity, f"annual_{k}"]) if entity in fa.index else 0.0
            row[f"estimated_{k}"] = round(est, 1)
            row[f"realised_{k}"] = round(realised, 1)
            row[f"realisation_{k}"] = round(realised / est, 2) if est > 0 else None
        ratio = row["realisation_co2e_kg"] or row["realisation_cost"]
        row["verdict"] = ("on track" if ratio is not None and 0.8 <= ratio <= 1.25
                          else "under-delivered" if ratio is not None and ratio < 0.8
                          else "over-delivered" if ratio is not None else "n/a")
        rows.append(row)
    return pd.DataFrame(rows)


def verify(opp_ids: list[str], seed: int = 42, settings: Settings | None = None) -> pd.DataFrame:
    """Simulate implementing ``opp_ids`` on synthetic data and compare with the estimate."""
    settings = settings or load_settings()
    ids = [i for i in opp_ids if i in SIMULATABLE]
    before = run(generate(seed), settings)
    after = run(generate(seed, applied=ids), settings)
    return compare(before, after, ids)
