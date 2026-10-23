"""CLI edge cases from the brief: its literal example path, and live mode without a key."""
from typer.testing import CliRunner

import main

from .conftest import ROOT


def _isolated(monkeypatch, tmp_path):
    """Run the CLI on a temporary database with no runs/ folder and no key."""
    from invoice_agents.graph import make_context
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr(main, "load_dotenv", lambda: None)
    monkeypatch.setenv("INVENTORY_DB", str(tmp_path / "cli.db"))
    monkeypatch.setattr(main, "make_context", lambda **kw: make_context(**(kw | {"runs_dir": None})))
    monkeypatch.setattr(main, "write_artifacts", lambda *a, **k: None)
    monkeypatch.chdir(ROOT)


def test_brief_example_path_runs_the_matching_sample(monkeypatch, tmp_path):
    """The brief's literal command names invoice1.txt, which the case data does not have: it runs
    invoice_1001.txt with a note instead of failing."""
    _isolated(monkeypatch, tmp_path)
    r = CliRunner().invoke(main.app, ["--invoice_path=data/invoices/invoice1.txt"])
    assert r.exit_code == 0, r.output
    assert "invoice1.txt is not in the case data" in r.output and "invoice_1001.txt" in r.output
    assert "Paid 5000.0 to Widgets Inc." in r.output


def test_missing_path_without_a_sample_exits_2_with_suggestion(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    r = CliRunner().invoke(main.app, ["--invoice_path=data/invoices/invoice_1O01.txt"])
    assert r.exit_code == 2 and "No such file" in r.output and "invoice_1001.txt" in r.output


def test_live_without_key_exits_2_cleanly(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr(main, "load_dotenv", lambda: None)
    monkeypatch.chdir(ROOT)
    r = CliRunner().invoke(main.app, ["--batch", "data/invoices_extra", "--mode", "live"])
    assert r.exit_code == 2 and "XAI_API_KEY is not set" in r.output


def test_evals_live_without_key_exits_2(monkeypatch, capsys):
    from evals import runner
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    assert runner.main(["--live", "--no-write"]) == 2
