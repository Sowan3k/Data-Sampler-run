"""Load and lightly validate config.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REQUIRED_TOP = ("study_period", "seeds", "prescreen", "search", "gemini", "storage")


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    missing = [key for key in REQUIRED_TOP if key not in cfg]
    if missing:
        raise ValueError(f"config.yaml is missing sections: {', '.join(missing)}")
    seeds = cfg["seeds"]
    for key in ("videos", "handles", "channel_ids"):
        seeds[key] = seeds.get(key) or []
    cfg["study_period"].setdefault("timezone_offset_hours", 6)
    cfg["storage"].setdefault("api_data_max_age_days", 30)
    return cfg
