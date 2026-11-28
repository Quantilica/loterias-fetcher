"""Pytest configuration and fixtures for loterias-fetcher."""

from __future__ import annotations

import pytest

from loterias_fetcher import plugin
from loterias_fetcher.client import LoteriasClient
from loterias_fetcher.constants import DEFAULT_API_HOST


class _SemRede(LoteriasClient):
    """``LoteriasClient`` do plugin sem ler o ``params.txt`` da Caixa nos testes."""

    def resolve_api_host(self) -> str:
        return self._api_host or DEFAULT_API_HOST


@pytest.fixture(autouse=True)
def _plugin_sem_rede(monkeypatch: pytest.MonkeyPatch) -> None:
    """O plugin não consulta a rede para achar o host; os testes que querem a
    resolução trocam ``plugin.LoteriasClient`` por um dublê próprio."""
    monkeypatch.setattr(plugin, "LoteriasClient", _SemRede)
