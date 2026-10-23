"""Lint (ruff E4, E7, E9, F) and type check (mypy) gates. CI installs requirements.txt, which pins both,
so these run on every push; locally they skip only if the tools are not installed."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run(tool: str, *args: str) -> subprocess.CompletedProcess:
    if importlib.util.find_spec(tool) is None:
        pytest.skip(f"{tool} not installed (pip install -r requirements-dev.txt)")
    return subprocess.run([sys.executable, "-m", tool, *args], cwd=ROOT, capture_output=True, text=True)


def test_ruff_clean():
    r = _run("ruff", "check", "--isolated", "--select", "E4,E7,E9,F", ".")
    assert r.returncode == 0, r.stdout + r.stderr


def test_mypy_clean():
    r = _run("mypy", "invoice_agents", "main.py", "--ignore-missing-imports")
    assert r.returncode == 0, r.stdout + r.stderr
