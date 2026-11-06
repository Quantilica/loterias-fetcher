"""Typer plugin for quantilica-cli integration."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any

from quantilica.cli.sdk import FetcherApp, make_resolve_groups
from quantilica.core.logging import get_logger
from quantilica.core.sync import FreshnessPolicy

from .catalog import GROUP_ALIASES, GROUPS, list_datasets
from .client import LoteriasClient
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


fetcher = FetcherApp(
    name="loterias",
    help="Resultados históricos e rateio das Loterias da Caixa Econômica Federal.",
    groups_dict=GROUPS,
    aliases_dict=GROUP_ALIASES,
    list_datasets=list_datasets,
    path_builder=path_builder,
    default_output=Path("/data/loterias"),
    freshness_policy=FreshnessPolicy.REMOTE_ONLY,
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


def _run_backfill_unit(unit: str, output_dir: Path | None = None) -> None:
    """Download single contest JSON with manifest sidecar."""
    client = LoteriasClient()
    slug, contest_s = unit.split(":", 1)
    contest_num = int(contest_s)
    base_dir = output_dir or (
        Path(os.environ.get("DATA_DIR", "~/data")).expanduser() / "loterias"
    )
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
