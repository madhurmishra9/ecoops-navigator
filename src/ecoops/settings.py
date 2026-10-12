"""Configuration loading: packaged defaults, optional override directory, in-memory overrides."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILES = ("factors", "rules", "constraints", "scoring")


def deep_merge(base: dict, override: dict | None) -> dict:
    """Return a new dict with ``override`` merged recursively into ``base``."""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _read_default(name: str) -> dict:
    text = resources.files("ecoops.defaults").joinpath(f"{name}.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


@dataclass(frozen=True)
class Settings:
    factors: dict[str, Any]
    rules: dict[str, Any]
    constraints: dict[str, Any]
    scoring: dict[str, Any]

    @property
    def currency(self) -> str:
        return self.factors.get("meta", {}).get("currency", "GBP")

    def with_overrides(
        self,
        factors: dict | None = None,
        rules: dict | None = None,
        constraints: dict | None = None,
        scoring: dict | None = None,
    ) -> Settings:
        return Settings(
            factors=deep_merge(self.factors, factors),
            rules=deep_merge(self.rules, rules),
            constraints=deep_merge(self.constraints, constraints),
            scoring=deep_merge(self.scoring, scoring),
        )


def load_settings(config_dir: str | Path | None = None) -> Settings:
    """Load packaged defaults, then merge any ``<name>.yaml`` found in ``config_dir``.

    ``config_dir`` falls back to the ``ECOOPS_CONFIG_DIR`` environment variable.
    """
    config_dir = config_dir or os.environ.get("ECOOPS_CONFIG_DIR")
    loaded: dict[str, dict] = {}
    for name in CONFIG_FILES:
        cfg = _read_default(name)
        if config_dir:
            path = Path(config_dir) / f"{name}.yaml"
            if path.exists():
                cfg = deep_merge(cfg, yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        loaded[name] = cfg
    return Settings(**loaded)
