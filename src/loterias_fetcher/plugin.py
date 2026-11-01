"""Typer plugin for quantilica-cli integration."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from quantilica.cli.sdk import FetcherApp, make_resolve_groups

from .catalog import GROUP_ALIASES, GROUPS, list_datasets
from .client import LoteriasClient
from .constants import MODALIDADES
from .storage import DataRepository

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
        raise RuntimeError(
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
        except Exception:
            pass
    return units


def _run_backfill_unit(unit: str) -> None:
    """Download single contest JSON."""
    client = LoteriasClient()
    slug, contest_s = unit.split(":", 1)
    contest_num = int(contest_s)
    out_dir = Path("/data/loterias/detalhe")
    out_dir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().strftime("%Y%m%d")
    out_file = out_dir / f"{slug}_{contest_num}@{today}.json"
    if not out_file.exists():
        data = client.get_contest(slug, contest_num)
        import json

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)


fetcher.command_backfill(
    lambda: _get_backfill_units(),
    lambda u: _run_backfill_unit(u),
    name="backfill",
    help="Carga histórica exaustiva de rateio e municípios ganhadores (JSON)",
)

app = fetcher.app
