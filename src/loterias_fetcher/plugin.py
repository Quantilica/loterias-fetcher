"""Typer plugin for quantilica-cli integration."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import os
from pathlib import Path
from typing import Any

import typer
from quantilica.cli.sdk import FetcherApp, default_client, make_resolve_groups
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
from .client import LoteriasClient, host_policies
from .constants import MODALIDADES
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

    def download_datasets(
        self,
        entries: list[dict[str, Any]],
        output_dir: Path,
        workers: int = 4,
        *,
        force: bool = False,
    ) -> tuple[int, int, list[tuple[str, str]]]:
        """Baixa as entradas em paralelo, todas pelo mesmo cliente.

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
        workers = self._limit_workers(client, entries, workers)
        console = get_console()
        total = len(entries)
        overall = make_batch_progress(console)
        file_prog = make_download_progress(console)
        overall_task = overall.add_task("[cyan]Baixando...[/cyan]", total=total)
        pool = ProgressPool(workers=workers, file_prog=file_prog)
        downloaded = 0
        errors: list[tuple[str, str]] = []

        def _worker(entry: dict[str, Any]) -> bool:
            eid = entry.get("id", "unknown")
            try:
                with pool.acquire(description=f"[cyan]{eid}[/cyan]") as cb:
                    self.download_entry(entry, output_dir, progress=cb, force=force)
                return True
            except Exception as exc:  # noqa: BLE001 - vira linha do relatório
                errors.append((eid, str(exc)))
                return False

        client = self.client
        if not isinstance(client, HttpClient):
            raise TypeError(
                "loterias exige um HttpClient, não " + type(client).__name__
            )
        with client:  # conexões persistentes, compartilhadas
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
def _get_backfill_units() -> list[str]:
    """Return units for backfill: list of all contest keys (e.g. megasena:3000)."""
    client = LoteriasClient()
    units: list[str] = []
    for slug in MODALIDADES:
        try:
            latest = client.get_contest(slug)
            num = latest.get("numero") or latest.get("concurso")
            if num:
                for c in range(1, int(num) + 1):
                    units.append(f"{slug}:{c}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Backfill: modalidade %s ignorada (último concurso indisponível): %s",
                slug,
                exc,
            )
    return units


def _default_data_dir() -> Path:
    """Padrão XDG quando ``DATA_DIR`` não está definido."""
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "quantilica"


def _run_backfill_unit(unit: str, output_dir: Path | None = None) -> None:
    """Download single contest JSON with manifest sidecar."""
    client = LoteriasClient()
    slug, contest_s = unit.split(":", 1)
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
