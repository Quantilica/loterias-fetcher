"""Tests for loterias-fetcher Typer plugin and backfill command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
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


class FakeClient:
    """Dublê de ``LoteriasClient``: conta as instâncias e as chamadas."""

    instances = 0

    def __init__(self, *args, **kwargs) -> None:
        type(self).instances += 1
        self.downloads: list[tuple[str, int]] = []

    def get_contest(self, slug: str, number: int | None = None) -> dict:
        if slug == "megasena":
            raise RuntimeError("503 fora do ar")
        return {"numero": 2}

    def download_contest(self, slug: str, number: int, dest: Path) -> Path:
        self.downloads.append((slug, number))
        dest.write_text("{}", encoding="utf-8")
        return dest


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    from loterias_fetcher import plugin

    FakeClient.instances = 0
    monkeypatch.setattr(plugin, "LoteriasClient", FakeClient)
    monkeypatch.setattr(plugin, "build_client", lambda: object())
    monkeypatch.setattr(plugin, "_backfill_client", None)
    return FakeClient


def test_backfill_units_loga_modalidade_com_falha(fake_client, caplog) -> None:
    """Modalidade que falha é registrada em warning e vira unidade com erro."""
    from loterias_fetcher import plugin

    with caplog.at_level("WARNING"):
        units = plugin._get_backfill_units()
    assert "megasena:1" not in units
    assert "megasena:ultimo" in units  # a falha não some da lista
    assert any(u.endswith(":2") for u in units)
    assert "megasena" in caplog.text
    assert "503 fora do ar" in caplog.text


def test_backfill_com_modalidade_indisponivel_sai_com_erro(
    fake_client, tmp_path: Path
) -> None:
    """A falha de uma modalidade reflete na saída (antes saía 0) e no checkpoint."""
    runner = CliRunner()
    result = runner.invoke(app, ["backfill", "-o", str(tmp_path)])
    assert result.exit_code == 1
    assert "megasena:ultimo" in result.output
    assert "503 fora do ar" in result.output
    checkpoint = json.loads((tmp_path / ".backfill" / "backfill.json").read_text())
    assert set(checkpoint["failed"]) == {"megasena:ultimo"}
    # as demais modalidades foram baixadas
    assert len(list((tmp_path / "detalhe").glob("quina_*.json"))) == 2


def test_backfill_usa_um_unico_cliente_por_execucao(
    fake_client, tmp_path: Path
) -> None:
    CliRunner().invoke(app, ["backfill", "-o", str(tmp_path)])
    assert fake_client.instances == 1


def test_backfill_sem_numero_do_concurso_e_falha(
    fake_client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        fake_client,
        "get_contest",
        lambda self, slug, number=None: {"numero": 0},
    )
    result = CliRunner().invoke(app, ["backfill", "-o", str(tmp_path)])
    assert result.exit_code == 1
    assert "sem o número do concurso" in result.output
