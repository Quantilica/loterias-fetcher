"""Tests for loterias-fetcher Typer plugin and backfill command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from loterias_fetcher.plugin import app


def test_cli_list() -> None:
    """Test quantilica loterias list."""
    runner = CliRunner()
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "concursos" in result.output
    assert "megasena" in result.output


def test_cli_backfill(tmp_path: Path, monkeypatch) -> None:
    """Test quantilica loterias backfill."""
    # Mock _get_backfill_units and _run_backfill_unit
    executed = []

    def mock_get_units():
        return ["megasena:1", "megasena:2"]

    def mock_run_unit(unit: str):
        executed.append(unit)

    from loterias_fetcher import plugin

    monkeypatch.setattr(plugin, "_get_backfill_units", mock_get_units)
    monkeypatch.setattr(plugin, "_run_backfill_unit", mock_run_unit)

    runner = CliRunner()
    result = runner.invoke(app, ["backfill", "-o", str(tmp_path)])
    assert result.exit_code == 0
    assert executed == ["megasena:1", "megasena:2"]
