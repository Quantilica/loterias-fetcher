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


def test_backfill_units_loga_modalidade_com_falha(monkeypatch, caplog) -> None:
    """Modalidade que falha é registrada em warning, sem derrubar as demais."""
    from loterias_fetcher import plugin

    class FakeClient:
        def get_contest(self, slug: str) -> dict:
            if slug == "megasena":
                raise RuntimeError("503 fora do ar")
            return {"numero": 2}

    monkeypatch.setattr(plugin, "LoteriasClient", FakeClient)
    with caplog.at_level("WARNING"):
        units = plugin._get_backfill_units()
    assert "megasena:1" not in units
    assert any(u.endswith(":2") for u in units)
    assert "megasena" in caplog.text
    assert "503 fora do ar" in caplog.text
