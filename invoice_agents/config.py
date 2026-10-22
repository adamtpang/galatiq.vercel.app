"""Policy loading. Business rules live in config/policy.yaml."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from . import ROOT

POLICY_PATH = ROOT / "config" / "policy.yaml"


@lru_cache(maxsize=4)
def load_policy(path: str | None = None) -> dict[str, Any]:
    with open(Path(path) if path else POLICY_PATH) as fh:
        return yaml.safe_load(fh)
