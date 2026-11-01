"""Tests for LoteriasClient."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from quantilica.core.http import HttpClient

from loterias_fetcher.client import LoteriasClient
from loterias_fetcher.constants import DEFAULT_API_HOST, MODALIDADES


def test_download_url_super_7() -> None:
    """Super 7 must use 'Super 7' in query param, not 'Super Sete'."""
    client = LoteriasClient()
    url = client.download_url_for_modalidade("supersete")
    assert "modalidade=Super%207" in url or "modalidade=Super 7" in url


def test_download_url_all_modalidades() -> None:
    """Every modalidade has a valid download URL."""
    client = LoteriasClient()
    for slug, mod in MODALIDADES.items():
        url = client.download_url_for_modalidade(slug)
        assert mod.download_name in url or mod.download_name.replace(" ", "%20") in url


def test_unknown_modalidade() -> None:
    """Unknown modalidade raises ValueError."""
    client = LoteriasClient()
    with pytest.raises(ValueError, match="Modalidade desconhecida"):
        client.download_url_for_modalidade("inexistente")

    with pytest.raises(ValueError, match="Modalidade desconhecida"):
        client.contest_url("inexistente")


def test_resolve_api_host_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve API host from params.txt."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "urlapiloterias": "https://servicebus3.caixa.gov.br/portaldeloterias"
    }

    monkeypatch.setattr(HttpClient, "get", lambda self, url, **kw: mock_resp)
    client = LoteriasClient()
    host = client.resolve_api_host()
    assert host == "https://servicebus3.caixa.gov.br/portaldeloterias"


def test_resolve_api_host_fallback_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fall back to DEFAULT_API_HOST when params.txt fails."""

    def mock_get(self, url, **kwargs):
        raise RuntimeError("network failure")

    monkeypatch.setattr(HttpClient, "get", mock_get)
    client = LoteriasClient()
    host = client.resolve_api_host()
    assert host == DEFAULT_API_HOST
