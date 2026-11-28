"""``sync``: host resolvido pelo params.txt, contadores do resumo e download validado.

Sem rede: ``httpx2.MockTransport`` faz o papel da API da Caixa.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx2
import pytest
from quantilica.core.exceptions import CorruptPayloadError
from quantilica.core.http import HostPolicy, HttpClient
from typer.testing import CliRunner

from loterias_fetcher import plugin
from loterias_fetcher.catalog import list_datasets
from loterias_fetcher.client import LoteriasClient
from loterias_fetcher.constants import DEFAULT_API_HOST, PARAMS_URL
from loterias_fetcher.plugin import fetcher

NOVO_HOST = "https://servicebus9.example.test/portaldeloterias"


class Api:
    """API falsa: registra as URLs pedidas e responde JSON (ou o que for dito)."""

    def __init__(self, *, params: Any = None, fail_ids: tuple[str, ...] = ()) -> None:
        self.params = params
        self.fail_ids = fail_ids
        self.urls: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        self.urls.append(url)
        if url == PARAMS_URL:
            if self.params is None:
                return httpx2.Response(500, text="erro")
            return httpx2.Response(200, text=json.dumps(self.params))
        if any(f"/api/{slug}" in url for slug in self.fail_ids):
            return httpx2.Response(404, text="nao achei")
        return httpx2.Response(
            200,
            content=b'{"numero": 1}',
            headers={"Content-Type": "application/json"},
        )

    def client(self) -> HttpClient:
        c = HttpClient(transport=httpx2.MockTransport(self))
        c.attempts = 1
        return c


@pytest.fixture
def com_resolucao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Devolve ao plugin o ``LoteriasClient`` real (o autouse o troca)."""
    monkeypatch.setattr(plugin, "LoteriasClient", LoteriasClient)


def _app(monkeypatch: pytest.MonkeyPatch, api: Api) -> Any:
    monkeypatch.setattr(fetcher, "client", api.client())
    return fetcher


def test_sync_usa_o_host_do_params(
    monkeypatch: pytest.MonkeyPatch, com_resolucao: None, tmp_path: Path
) -> None:
    api = Api(params={"urlapiloterias": NOVO_HOST + "/"})
    app = _app(monkeypatch, api)
    rapida = HostPolicy(min_interval=0.0, max_concurrency=2)
    monkeypatch.setattr(plugin, "host_policy", lambda: rapida)
    entries = list_datasets("detalhe")

    ok, total, errors = app.download_datasets(entries, tmp_path, workers=2)

    assert (ok, total, errors) == (11, 11, [])
    api_urls = [u for u in api.urls if u != PARAMS_URL]
    assert api_urls and all(u.startswith(NOVO_HOST) for u in api_urls)
    assert not any(DEFAULT_API_HOST in u for u in api.urls)
    assert api.urls.count(PARAMS_URL) == 1  # uma leitura por execução
    # o host novo passa a ter a política de tráfego
    assert app.client.host_policies["servicebus9.example.test"] is rapida
    # o catálogo em si não é alterado
    assert all(e["url"].startswith(DEFAULT_API_HOST) for e in entries)


def test_params_fora_do_ar_cai_no_host_fixo_e_avisa(
    monkeypatch: pytest.MonkeyPatch,
    com_resolucao: None,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = Api(params=None)  # params.txt devolve 500
    app = _app(monkeypatch, api)

    with caplog.at_level(logging.WARNING):
        ok, total, errors = app.download_datasets(
            list_datasets("detalhe"), tmp_path, workers=2
        )

    assert (ok, total, errors) == (11, 11, [])
    assert all(u.startswith(DEFAULT_API_HOST) for u in api.urls if u != PARAMS_URL)
    assert "params.txt" in caplog.text and "usando o host padrão" in caplog.text


def test_contadores_preenchidos_com_sucesso_e_falha(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    api = Api(fail_ids=("quina",))
    app = _app(monkeypatch, api)
    app.last_download_stats = None

    ok, total, errors = app.download_datasets(
        list_datasets("detalhe"), tmp_path, workers=2
    )

    assert (ok, total) == (10, 11)
    assert [e[0] for e in errors] == ["quina_ultimo"]
    stats = app.last_download_stats
    assert stats is not None
    assert stats.succeeded_count == 10 and stats.failed_count == 1


def test_summary_json_do_sync_tem_contadores_e_saida_3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    api = Api(fail_ids=("quina",))
    _app(monkeypatch, api)
    summary = tmp_path / "resumo.json"

    result = CliRunner().invoke(
        plugin.app,
        [
            "sync",
            "detalhe",
            "-o",
            str(tmp_path / "out"),
            "--summary-json",
            str(summary),
        ],
    )

    assert result.exit_code == 3
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["total"] == 11 and data["succeeded"] == 10 and data["failed"] == 1
    assert data["downloaded"] == 10 and data["bytes_downloaded"] > 0
    assert data["errors"][0]["id"] == "quina_ultimo"


# --- cliente: JSON validado no download do backfill ---------------------------


def test_download_contest_rejeita_html_com_200(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == PARAMS_URL:
            return httpx2.Response(500)
        return httpx2.Response(
            200,
            text="<html><body>Manutencao</body></html>",
            headers={"Content-Type": "text/html"},
        )

    http = HttpClient(transport=httpx2.MockTransport(handler))
    http.attempts = 1
    dest = tmp_path / "megasena_1@20261101.json"
    with pytest.raises(CorruptPayloadError):
        LoteriasClient(http).download_contest("megasena", 1, dest)
    assert not dest.exists()


def test_download_contest_json_valido_grava_arquivo_e_manifesto(
    tmp_path: Path,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == PARAMS_URL:
            return httpx2.Response(500)
        return httpx2.Response(200, content=b'{"numero": 1}')

    http = HttpClient(transport=httpx2.MockTransport(handler))
    http.attempts = 1
    dest = tmp_path / "megasena_1@20261101.json"
    # sem mock do método do core: a chamada real tem de ter todos os argumentos
    LoteriasClient(http).download_contest("megasena", 1, dest)
    assert json.loads(dest.read_text()) == {"numero": 1}
    manifest = json.loads(Path(f"{dest}.manifest.json").read_text())
    assert manifest["source_id"] == "loterias"
