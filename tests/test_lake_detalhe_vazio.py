"""Detalhe do concurso sem linhas num dataset: o membro vai vazio, com a origem.

No bruto, ``detalhe/<modalidade>@<carimbo>.json`` é um arquivo por modalidade (o
concurso mais recente) e a versão nova substitui a anterior. Quando o concurso não
teve ganhador (``listaMunicipioUFGanhadores`` vazia), o conversor não gravava o
membro de ``ganhadores_municipio``: o lake ficava com o membro da versão anterior,
cuja origem já não é a vigente (``origem_superada`` na auditoria).
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
from quantilica.analytics.lake import check_dataset
from quantilica.analytics.lake_audit import lake_audit

from loterias_fetcher.lake import converter

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SOURCE = "loterias"


def _snapshot(raw: Path, stamp: str, concurso: int, *, ganhadores: bool) -> Path:
    detalhe = raw / "detalhe"
    detalhe.mkdir(parents=True, exist_ok=True)
    data = json.loads((FIXTURES_DIR / "megasena_3000.json").read_text())
    data["numero"] = concurso
    if not ganhadores:
        data["listaMunicipioUFGanhadores"] = []
    dest = detalhe / f"megasena@{stamp}.json"
    dest.write_text(json.dumps(data), encoding="utf-8")
    return dest


def _achados(lake: Path, raw: Path) -> dict[str, int]:
    report = lake_audit(
        lake,
        input_dir=raw,
        sources=[SOURCE],
        readers=False,
        integrity=False,
        converters={SOURCE: converter},
    )
    return {
        k: v
        for k, v in report.by_category().items()
        if k
        in {"origem_superada", "versao_duplicada", "sem_parquet", "sha256_divergente"}
    }


def _parquet(lake: Path, dataset: str) -> Path:
    (path,) = (lake / SOURCE / dataset).rglob("megasena.parquet")
    return path


def test_concurso_sem_ganhador_substitui_o_membro_anterior(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    lake = tmp_path / "lake"
    lake.mkdir()

    _snapshot(raw, "20261109", 3000, ganhadores=True)
    res = converter.convert(raw, lake)
    assert (res.converted, res.errors) == (2, [])
    assert pl.read_parquet(_parquet(lake, "ganhadores_municipio")).height == 1
    assert _achados(lake, raw) == {}

    # Concurso seguinte, sem ganhador por município: a versão nova do arquivo.
    _snapshot(raw, "20261123", 3001, ganhadores=False)
    res = converter.convert(raw, lake)
    assert (res.converted, res.errors) == (2, [])
    for ds in ("rateio", "ganhadores_municipio"):
        assert not check_dataset(lake / SOURCE / ds)
    vazio = pl.read_parquet(_parquet(lake, "ganhadores_municipio"))
    assert vazio.height == 0
    assert vazio.schema["ganhadores"] == pl.Int64 and "municipio" in vazio.columns
    assert pl.read_parquet(_parquet(lake, "rateio"))["concurso"].unique().to_list() == [
        3001
    ]
    assert _achados(lake, raw) == {}

    # Reexecutar não reescreve nada.
    res = converter.convert(raw, lake)
    assert (res.converted, res.skipped) == (0, 2)


def test_membro_vazio_volta_a_ter_linhas_na_versao_seguinte(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    lake = tmp_path / "lake"
    lake.mkdir()
    _snapshot(raw, "20261123", 3001, ganhadores=False)
    converter.convert(raw, lake)
    assert pl.read_parquet(_parquet(lake, "ganhadores_municipio")).height == 0

    _snapshot(raw, "20261125", 3002, ganhadores=True)
    res = converter.convert(raw, lake)
    assert (res.converted, res.errors) == (2, [])
    df = pl.read_parquet(_parquet(lake, "ganhadores_municipio"))
    assert df["concurso"].to_list() == [3002]
    assert _achados(lake, raw) == {}
