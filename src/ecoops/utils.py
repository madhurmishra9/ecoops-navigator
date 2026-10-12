"""Small shared helpers."""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd


def _default(obj: Any) -> Any:
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        value = float(obj)
        return None if math.isnan(value) else value
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, set):
        return sorted(obj)
    return str(obj)


def _clean_nan(obj: Any) -> Any:
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    return obj


def to_jsonable(obj: Any) -> Any:
    """Convert numpy/pandas values into plain JSON-safe Python objects (NaN -> None)."""
    return _clean_nan(json.loads(json.dumps(obj, default=_default)))


def fmt_qty(value: float, unit: str = "") -> str:
    """Human-friendly number for reports: 12345 -> '12.3k'."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000:
        text = f"{v / 1_000_000:.2f}M"
    elif v >= 1_000:
        text = f"{v / 1_000:.1f}k"
    elif v >= 10:
        text = f"{v:.0f}"
    else:
        text = f"{v:.2f}"
    return f"{sign}{text}{(' ' + unit) if unit else ''}"
