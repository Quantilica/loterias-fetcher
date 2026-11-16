"""Política por host da API da Caixa: espaçamento, simultaneidade e 429.

Um servidor HTTP falso (thread local) faz o papel da API. Ele recusa com 429,
com e sem ``Retry-After``, parte das chamadas, e registra o instante de cada
requisição e quantas estão em curso ao mesmo tempo.
"""

from __future__ import annotations

import io
import json
import threading
import time
import zipfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from quantilica.core.http import HostPolicy

from loterias_fetcher.catalog import list_datasets
from loterias_fetcher.client import API_HOSTS, host_policies, host_policy
from loterias_fetcher.plugin import LoteriasFetcherApp, build_client, fetcher

LOCAL = "127.0.0.1"


def _xlsx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
    return buf.getvalue()


class FakeApi:
    """API falsa: 429 em parte das chamadas e métricas de tráfego."""

    def __init__(
        self,
        *,
        refuse_first: int = 0,
        global_refuse: int = 0,
        retry_after: str | None = None,
    ):
        self.refuse_first = refuse_first  # 429 por caminho antes do 200
        self.global_refuse = global_refuse  # 429 nas primeiras N chamadas no total
        self.retry_after = retry_after  # Retry-After dos 429 (None: sem cabeçalho)
        self.lock = threading.Lock()
        self.arrivals: list[float] = []
        self.refusals: list[float] = []
        self.hits: dict[str, int] = {}
        self.inflight = 0
        self.max_inflight = 0
        self.service_time = 0.02
        server = ThreadingHTTPServer((LOCAL, 0), self._handler())
        server.daemon_threads = True
        self.server = server
        self.port = server.server_address[1]
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        api = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # silencioso
                pass

            def _serve(self, send_body: bool) -> None:
                path = self.path
                with api.lock:
                    now = time.monotonic()
                    api.arrivals.append(now)
                    api.inflight += 1
                    api.max_inflight = max(api.max_inflight, api.inflight)
                    api.hits[path] = n = api.hits.get(path, 0) + 1
                    total_hits = len(api.arrivals)
                try:
                    time.sleep(api.service_time)
                    if n <= api.refuse_first or total_hits <= api.global_refuse:
                        self.send_response(429)
                        # Com refuse_first, só os caminhos de tamanho par levam
                        # Retry-After: cobre as duas formas de 429.
                        if api.retry_after and (
                            api.global_refuse or len(path) % 2 == 0
                        ):
                            self.send_header("Retry-After", api.retry_after)
                        body = b"<html>Too Many Requests</html>"
                        self.send_header("Content-Type", "text/html")
                        with api.lock:
                            api.refusals.append(time.monotonic())
                    else:
                        self.send_response(200)
                        if "download" in path:
                            body = _xlsx_bytes()
                            ctype = "application/octet-stream"
                        else:
                            body = json.dumps({"numero": 1, "path": path}).encode()
                            ctype = "application/json"
                        self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    if send_body:
                        self.wfile.write(body)
                finally:
                    with api.lock:
                        api.inflight -= 1

            def do_GET(self) -> None:  # noqa: N802
                self._serve(True)

            def do_HEAD(self) -> None:  # noqa: N802
                self._serve(False)

        return Handler

    def entries(self) -> list[dict[str, Any]]:
        """As 22 entradas do catálogo (11 XLSX + 11 JSON) apontando para cá."""
        out = []
        for entry in list_datasets():
            e = dict(entry)
            tail = e["url"].split("/portaldeloterias", 1)[1]
            e["url"] = f"http://{LOCAL}:{self.port}{tail}"
            out.append(e)
        return out


@pytest.fixture
def api_factory() -> Iterator[Any]:
    started: list[FakeApi] = []

    def make(**kwargs: Any) -> FakeApi:
        api = FakeApi(**kwargs)
        api.thread.start()
        started.append(api)
        return api

    yield make
    for api in started:
        api.server.shutdown()
        api.server.server_close()
        api.thread.join(timeout=5)


def _app(policy: HostPolicy) -> LoteriasFetcherApp:
    """O app do plugin, com cliente que protege só o servidor falso."""
    client = build_client()
    client.host_policies.clear()
    client.host_policies.update(host_policies((LOCAL,), policy))
    client.retry_base_delay = 0.01
    client.jitter = 0.0
    client.attempts = 6
    app = fetcher
    app.client = client
    return app


def test_politica_padrao_cobre_os_hosts_da_caixa() -> None:
    policies = host_policies()
    assert set(policies) == set(API_HOSTS)
    p = policies["servicebus3.caixa.gov.br"]
    assert p == host_policy()
    assert p.min_interval >= 1.0 and p.burst == 1
    assert p.backoff_base is not None and p.backoff_base > 0  # pausa o host no 429
    assert 0 < p.max_concurrency <= 4


def test_cliente_do_plugin_carrega_a_politica() -> None:
    client = build_client()
    assert set(API_HOSTS) <= set(client.host_policies)
    assert isinstance(fetcher, LoteriasFetcherApp)


@pytest.mark.parametrize("retry_after", [None, "0.1"])
def test_22_modalidades_terminam_com_429_intermitente(
    api_factory: Any, tmp_path: Path, retry_after: str | None
) -> None:
    """429 (com e sem Retry-After) nas primeiras chamadas de cada URL."""
    api = api_factory(refuse_first=1, retry_after=retry_after)
    entries = api.entries()
    assert len(entries) == 22
    policy = HostPolicy(
        min_interval=0.01, max_concurrency=2, burst=1, backoff_base=0.05
    )
    app = _app(policy)

    ok, total, errors = app.download_datasets(entries, tmp_path, workers=6)

    assert (ok, total, errors) == (22, 22, [])
    assert api.refusals, "o servidor falso deveria ter recusado ao menos uma vez"
    assert len(list(tmp_path.rglob("*.xlsx"))) == 11
    jsons = [p for p in tmp_path.rglob("*.json") if "manifest" not in p.name]
    assert len(jsons) == 11


def test_simultaneas_respeitam_a_politica(api_factory: Any, tmp_path: Path) -> None:
    api = api_factory()
    api.service_time = 0.08
    policy = HostPolicy(min_interval=0.005, max_concurrency=2, burst=1)
    app = _app(policy)

    ok, total, errors = app.download_datasets(api.entries(), tmp_path, workers=8)

    assert (ok, total, errors) == (22, 22, [])
    assert 1 <= api.max_inflight <= 2


def test_requisicoes_sao_espacadas(api_factory: Any, tmp_path: Path) -> None:
    api = api_factory()
    interval = 0.06
    policy = HostPolicy(min_interval=interval, max_concurrency=4, burst=1)
    app = _app(policy)

    ok, total, errors = app.download_datasets(api.entries(), tmp_path, workers=8)

    assert (ok, total, errors) == (22, 22, [])
    gaps = [b - a for a, b in zip(api.arrivals, api.arrivals[1:], strict=False)]
    # Folga para o relógio e o agendamento das threads do servidor falso.
    assert min(gaps) >= interval * 0.5
    assert (
        api.arrivals[-1] - api.arrivals[0] >= interval * (len(api.arrivals) - 1) * 0.8
    )


def test_429_pausa_o_host_inteiro(api_factory: Any, tmp_path: Path) -> None:
    """Depois de um 429 com Retry-After, nenhuma thread chama o host na pausa."""
    pausa = 0.6
    api = api_factory(global_refuse=1, retry_after=str(pausa))
    policy = HostPolicy(
        min_interval=0.01, max_concurrency=4, burst=1, backoff_base=0.05
    )
    app = _app(policy)

    ok, total, errors = app.download_datasets(api.entries(), tmp_path, workers=4)

    assert (ok, total, errors) == (22, 22, [])
    assert len(api.refusals) == 1
    t429 = api.refusals[0]
    # Requisições já a caminho quando veio o 429 chegam em instantes; as demais
    # esperam a pausa do host inteiro, não só a thread que foi recusada.
    janela = [a for a in api.arrivals if t429 + 0.2 < a < t429 + pausa - 0.1]
    assert janela == []
    assert any(a >= t429 + pausa - 0.05 for a in api.arrivals)


def test_workers_limitados_pelo_max_concurrency() -> None:
    client = build_client()
    client.host_policies.clear()
    client.host_policies.update(
        host_policies((LOCAL,), HostPolicy(min_interval=0.0, max_concurrency=3))
    )
    entries = [{"url": f"http://{LOCAL}:1/x"}]
    limit = LoteriasFetcherApp._limit_workers
    assert limit(client, entries, 8) == 3
    assert limit(client, entries, 2) == 2
    # Host sem política: o número pedido vale.
    assert limit(client, [{"url": "http://outro.exemplo/x"}], 8) == 8
