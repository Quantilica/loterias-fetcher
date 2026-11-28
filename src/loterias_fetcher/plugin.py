"""Typer plugin for quantilica-cli integration."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import typer
from quantilica.cli.sdk import FetcherApp, default_client, make_resolve_groups
from quantilica.cli.summary import DownloadStats
from quantilica.cli.ui import (
    ProgressPool,
    get_console,
    graceful_executor,
    make_batch_progress,
    make_download_progress,
)
from quantilica.core.http import HttpClient
from quantilica.core.logging import get_logger
from quantilica.core.registry import FetcherInfo
from quantilica.core.sync import FreshnessPolicy
from rich.console import Group
from rich.live import Live

from .catalog import GROUP_ALIASES, GROUPS, list_datasets
from .client import LoteriasClient, host_policies, host_policy
from .constants import DEFAULT_API_HOST, MODALIDADES
from .storage import DataRepository

logger = get_logger(__name__)

resolve_groups = make_resolve_groups(
    GROUPS, {alias: [canon] for alias, canon in GROUP_ALIASES.items()}
)


def path_builder(
    output_dir: Path, entry: dict[str, Any], last_modified: dt.date | None
) -> Path:
    """Build local storage path for a dataset entry."""
    return DataRepository(output_dir).path_for_entry(entry, last_modified=last_modified)


class LoteriasFetcherApp(FetcherApp):
    """``FetcherApp`` que baixa com UM cliente compartilhado entre as threads.

    O ``download_datasets`` padrão cria um ``HttpClient`` por thread, sem as
    políticas por host e com um limitador próprio em cada cliente: com vários
    ``--workers`` a API da Caixa recebe as requisições em paralelo e responde
    ``429``. Aqui todas as threads usam ``self.client``, de modo que o espaçamento,
    o limite de requisições simultâneas e a pausa do host no ``429`` (a
    ``HostPolicy`` de :mod:`loterias_fetcher.client`) valem para o conjunto.
    """

    @staticmethod
    def _limit_workers(
        client: HttpClient, entries: list[dict[str, Any]], workers: int
    ) -> int:
        """Limita as threads ao ``max_concurrency`` dos hosts das entradas.

        O ``HttpClient`` aplica ``max_concurrency`` nas chamadas ``request``
        (``HEAD``/``GET`` simples), mas não em ``stream`` (o download do
        arquivo). Como cada thread tem no máximo uma requisição em curso,
        limitar as threads garante o teto também no download.
        """
        caps = []
        for entry in entries:
            policy = client._policy_for(str(entry["url"]))
            if policy is not None and policy.max_concurrency > 0:
                caps.append(policy.max_concurrency)
        return max(1, min([workers, *caps]))

    def _entries_com_host_resolvido(
        self, client: HttpClient, entries: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[Any, dict[str, Any]]]:
        """Troca o host fixo do catálogo pelo que a Caixa publica em ``params.txt``.

        O catálogo grava ``DEFAULT_API_HOST`` em todas as URLs; a Caixa já mudou de
        host mais de uma vez. Uma única leitura do ``params.txt`` por execução; se
        ela falhar, vale o host fixo (e :meth:`LoteriasClient.resolve_api_host`
        registra o aviso). O endereço lido é validado (``https`` em
        ``.caixa.gov.br`` com o mesmo caminho base); outro valor é descartado com
        aviso e vale o fixo. O host resolvido entra na política de tráfego se ainda
        não estiver nela.

        Returns:
            tuple: As entradas (com o host resolvido) e, por ``id``, as entradas
            originais (host fixo) das que foram trocadas, para a nova tentativa.
        """
        host = LoteriasClient(client).resolve_api_host()
        if host == DEFAULT_API_HOST:
            return entries, {}
        logger.info(
            "Host da API pelo params.txt difere do fixo: usando %s (reserva: %s)",
            host,
            DEFAULT_API_HOST,
        )
        netloc = urlsplit(host).hostname
        if netloc and netloc not in client.host_policies:
            client.host_policies[netloc] = host_policy()
        originais: dict[Any, dict[str, Any]] = {}
        trocadas: list[dict[str, Any]] = []
        for e in entries:
            if str(e.get("url", "")).startswith(DEFAULT_API_HOST):
                originais[e.get("id")] = e
                e = {**e, "url": host + str(e["url"])[len(DEFAULT_API_HOST) :]}
            trocadas.append(e)
        return trocadas, originais

    def download_datasets(
        self,
        entries: list[dict[str, Any]],
        output_dir: Path,
        workers: int = 4,
        *,
        force: bool = False,
    ) -> tuple[int, int, list[tuple[str, str]]]:
        """Baixa as entradas em paralelo, todas pelo mesmo cliente.

        Os contadores ficam em ``last_download_stats`` (o ``--summary-json`` do
        ``sync`` os lê) e as URLs usam o host que a Caixa publica no
        ``params.txt``, com o fixo como reserva.

        Args:
            entries: Entradas do catálogo a baixar.
            output_dir: Diretório base de destino.
            workers: Threads de download (a política do host limita o tráfego).
            force: Ignora a checagem de frescor local e baixa tudo.

        Returns:
            tuple[int, int, list[tuple[str, str]]]: Baixadas, total e a lista
            ``(id, mensagem)`` das que falharam.
        """
        client = self.client
        if not isinstance(client, HttpClient):
            raise TypeError(
                "loterias exige um HttpClient, não " + type(client).__name__
            )
        console = get_console()
        total = len(entries)
        stats = self.last_download_stats = DownloadStats()
        downloaded = 0
        errors: list[tuple[str, str]] = []

        with client:  # conexões persistentes, compartilhadas
            entries, originais = self._entries_com_host_resolvido(client, entries)
            workers = self._limit_workers(client, entries, workers)
            overall = make_batch_progress(console)
            file_prog = make_download_progress(console)
            overall_task = overall.add_task("[cyan]Baixando...[/cyan]", total=total)
            pool = ProgressPool(workers=workers, file_prog=file_prog)

            def _worker(entry: dict[str, Any]) -> bool:
                eid = entry.get("id", "unknown")

                def _baixar(e: dict[str, Any]) -> Any:
                    with pool.acquire(description=f"[cyan]{eid}[/cyan]") as cb:
                        measured = stats.track().forwarding(cb)
                        self.download_entry(
                            e, output_dir, progress=measured, force=force
                        )
                        return measured

                try:
                    try:
                        measured = _baixar(entry)
                    except Exception as exc:
                        original = originais.get(entry.get("id"))
                        if original is None:
                            raise
                        logger.warning(
                            "%s falhou no host resolvido (%s); tentando o host fixo",
                            eid,
                            exc,
                        )
                        measured = _baixar(original)
                    stats.succeeded(measured)
                    return True
                except Exception as exc:  # noqa: BLE001 - vira linha do relatório
                    stats.failed()
                    errors.append((eid, str(exc)))
                    return False

            with graceful_executor(max_workers=workers) as executor:
                try:
                    with Live(
                        Group(overall, file_prog),
                        console=console,
                        refresh_per_second=10,
                    ):
                        futures = [executor.submit(_worker, e) for e in entries]
                        for future in concurrent.futures.as_completed(futures):
                            overall.update(overall_task, advance=1)
                            if future.result():
                                downloaded += 1
                except KeyboardInterrupt:
                    console.print("\n[yellow]Interrompido.[/yellow]")
                    raise typer.Exit(130) from None
        return downloaded, total, errors


def build_client() -> HttpClient:
    """Cliente padrão da CLI com a política de tráfego da API da Caixa."""
    client = default_client()
    client.host_policies.update(host_policies())
    return client


fetcher = LoteriasFetcherApp(
    name="loterias",
    help="Resultados históricos e rateio das Loterias da Caixa Econômica Federal.",
    info=FetcherInfo(
        id="loterias",
        nome="Loterias CAIXA",
        orgao="Caixa Econômica Federal",
        licenca=(
            "Sem licença declarada; dados públicos pela Lei 12.527/2011 (LAI) "
            "e Decreto 8.777/2016"
        ),
        homepage="https://loterias.caixa.gov.br",
        cadencia="irregular",
    ),
    groups_dict=GROUPS,
    aliases_dict=GROUP_ALIASES,
    list_datasets=list_datasets,
    path_builder=path_builder,
    default_output=Path("/data/loterias"),
    freshness_policy=FreshnessPolicy.REMOTE_ONLY,
    client=build_client(),
)


def convert(
    input_dir: Path,
    lake_dir: Path,
    *,
    dataset: list[str] | None = None,
    force: bool = False,
) -> Any:
    """Converte acervo bruto das loterias para o lake Hive (Parquet)."""
    try:
        from loterias_fetcher import lake
    except ImportError as exc:
        raise ImportError(
            "Conversão para o lake requer o extra 'analysis'. "
            "Instale com: quantilica install loterias --extra analysis"
        ) from exc
    return lake.converter.convert(input_dir, lake_dir, datasets=dataset, force=force)


fetcher.command_convert(convert)
fetcher.command_pipeline(convert)


# Register backfill subcommand (P5)
LATEST_UNIT = "ultimo"
"""Sufixo da unidade que marca uma modalidade cujo último concurso não veio."""

_backfill_client: LoteriasClient | None = None
_backfill_failures: dict[str, str] = {}


def _get_backfill_client(*, new: bool = False) -> LoteriasClient:
    """Cliente único da execução do backfill (o ``params.txt`` é lido uma vez)."""
    global _backfill_client
    if _backfill_client is None or new:
        _backfill_client = LoteriasClient(build_client())
    return _backfill_client


def _get_backfill_units() -> list[str]:
    """Return units for backfill: list of all contest keys (e.g. megasena:3000).

    Modalidade sem o último concurso (falha da API ou resposta sem o número) não
    é ignorada em silêncio: entra como a unidade ``<slug>:ultimo``, que falha ao
    rodar e faz o ``backfill`` terminar com erro.
    """
    client = _get_backfill_client(new=True)
    _backfill_failures.clear()
    units: list[str] = []
    for slug in MODALIDADES:
        try:
            latest = client.get_contest(slug)
            num = latest.get("numero") or latest.get("concurso")
            if not num:
                raise ValueError("resposta sem o número do concurso")
            for c in range(1, int(num) + 1):
                units.append(f"{slug}:{c}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Backfill: modalidade %s sem o último concurso: %s", slug, exc
            )
            _backfill_failures[slug] = str(exc)
            units.append(f"{slug}:{LATEST_UNIT}")
    return units


def _default_data_dir() -> Path:
    """Padrão XDG quando ``DATA_DIR`` não está definido."""
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "quantilica"


def _run_backfill_unit(unit: str, output_dir: Path | None = None) -> None:
    """Download single contest JSON with manifest sidecar."""
    slug, contest_s = unit.split(":", 1)
    if contest_s == LATEST_UNIT:
        cause = _backfill_failures.get(slug, "causa não registrada")
        raise RuntimeError(f"último concurso de {slug} indisponível: {cause}")
    client = _get_backfill_client()
    contest_num = int(contest_s)
    raiz = Path(os.environ.get("DATA_DIR") or _default_data_dir()).expanduser()
    base_dir = output_dir or (raiz / "loterias")
    out_dir = base_dir / "detalhe"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().strftime("%Y%m%d")
    out_file = out_dir / f"{slug}_{contest_num}@{today}.json"
    if not out_file.exists():
        client.download_contest(slug, contest_num, out_file)


def _run_backfill_wrapper(unit: str, output_dir: Path | None = None) -> None:
    import inspect

    sig = inspect.signature(_run_backfill_unit)
    if len(sig.parameters) >= 2:
        _run_backfill_unit(unit, output_dir)
    else:
        _run_backfill_unit(unit)


fetcher.command_backfill(
    lambda: _get_backfill_units(),
    _run_backfill_wrapper,
    name="backfill",
    help="Carga histórica exaustiva de rateio e municípios ganhadores (JSON)",
)

app = fetcher.app
