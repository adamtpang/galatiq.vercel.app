"""CLI edge cases from the brief: its literal example path, and live mode without a key."""
from typer.testing import CliRunner

import main

from .conftest import ROOT


def test_brief_example_path_exits_2_with_suggestion(monkeypatch):
    monkeypatch.chdir(ROOT)
    r = CliRunner().invoke(main.app, ["--invoice_path=data/invoices/invoice1.txt"])
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
