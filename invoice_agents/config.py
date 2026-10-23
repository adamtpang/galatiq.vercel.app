"""Policy loading. Business rules live in config/policy.yaml."""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from . import ROOT

POLICY_PATH = ROOT / "config" / "policy.yaml"


@lru_cache(maxsize=4)
def _load(path: str | None) -> dict[str, Any]:
    with open(Path(path) if path else POLICY_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_policy(path: str | None = None) -> dict[str, Any]:
    """A fresh copy each call, so a caller that changes its policy cannot change anyone else's."""
    return copy.deepcopy(_load(path))
