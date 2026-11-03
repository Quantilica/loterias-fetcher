"""Tests for loterias-fetcher lake conversion and check_dataset."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import polars as pl
from quantilica.analytics.lake import check_dataset

from loterias_fetcher.constants import MODALIDADES
from loterias_fetcher.lake import converter

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_converter_metadata() -> None:
    """Verify converter source_id and dataset list."""
    assert converter.source_id == "loterias"
    assert "concursos" in converter.datasets()
    assert "rateio" in converter.datasets()
    assert "ganhadores_municipio" in converter.datasets()


def test_convert_all_11_modalidades(tmp_path: Path) -> None:
    """Convert all 11 modalidade XLSX fixtures and JSON detail into lake."""
    raw_dir = tmp_path / "raw"
    concursos_raw = raw_dir / "concursos"
    detalhe_raw = raw_dir / "detalhe"
    concursos_raw.mkdir(parents=True)
    detalhe_raw.mkdir(parents=True)

    lake_dir = tmp_path / "lake"
    lake_dir.mkdir(parents=True)

    # Copy 11 XLSX fixtures into raw/concursos with timestamp stamp
    for slug in MODALIDADES:
        src = FIXTURES_DIR / f"{slug}.xlsx"
        assert src.is_file(), f"Missing fixture {src}"
        dest = concursos_raw / f"{slug}@20261101.xlsx"
        shutil.copy2(src, dest)

    # Copy JSON contest detail fixture into raw/detalhe
    json_src = FIXTURES_DIR / "megasena_3000.json"
    assert json_src.is_file()
    shutil.copy2(json_src, detalhe_raw / "megasena_3000@20261101.json")

    # Run conversion
    res = converter.convert(raw_dir, lake_dir)
    assert not res.errors, f"Conversion errors: {res.errors}"
    assert res.converted >= 13  # 11 modalidades concursos + 1 rateio + 1 ganhadores
    assert res.skipped == 0

    # Verify check_dataset passes on all 3 datasets
    for ds_name in ("concursos", "rateio", "ganhadores_municipio"):
        ds_dir = lake_dir / "loterias" / ds_name
        assert ds_dir.is_dir()
        errors = check_dataset(ds_dir)
        assert not errors, f"check_dataset failed for {ds_name}: {errors}"

    # Idempotency check: 2nd conversion skips already current files
    res2 = converter.convert(raw_dir, lake_dir)
    assert not res2.errors
    assert res2.skipped >= 11


def _detalhe(raw_dir: Path, concurso: int, stamp: str) -> Path:
    detalhe = raw_dir / "detalhe"
    detalhe.mkdir(parents=True, exist_ok=True)
    data = json.loads((FIXTURES_DIR / "megasena_3000.json").read_text())
    data["numero"] = concurso
    dest = detalhe / f"megasena_{concurso}@{stamp}.json"
    dest.write_text(json.dumps(data), encoding="utf-8")
    return dest


def _rows(dataset_dir: Path) -> pl.DataFrame:
    parts = sorted(dataset_dir.rglob("*.parquet"))
    return pl.concat([pl.read_parquet(p) for p in parts], how="diagonal")


def test_reconversao_com_concurso_novo_preserva_todos_os_concursos(
    tmp_path: Path,
) -> None:
    """Regressao A3: um concurso novo nao pode fazer o anterior ser pulado/perdido."""
    raw_dir = tmp_path / "raw"
    lake_dir = tmp_path / "lake"
    lake_dir.mkdir()

    _detalhe(raw_dir, 3000, "20261101")
    res1 = converter.convert(raw_dir, lake_dir)
    assert not res1.errors
    # 1 arquivo JSON -> 1 escrita em rateio + 1 em ganhadores_municipio
    assert (res1.converted, res1.skipped) == (2, 0)
    rateio = lake_dir / "loterias" / "rateio"
    ganhadores = lake_dir / "loterias" / "ganhadores_municipio"
    n_rateio, n_ganh = _rows(rateio).height, _rows(ganhadores).height
    assert n_rateio > 0 and n_ganh > 0

    _detalhe(raw_dir, 3001, "20261102")
    res2 = converter.convert(raw_dir, lake_dir)
    assert not res2.errors
    # o concurso 3000 e pulado (e contado como skipped, nao como converted)
    assert (res2.converted, res2.skipped) == (2, 2)

    for ds_dir, n in ((rateio, n_rateio), (ganhadores, n_ganh)):
        assert not check_dataset(ds_dir)
        df = _rows(ds_dir)
        assert df.height == 2 * n
        assert sorted(df["concurso"].unique().to_list()) == [3000, 3001]

    # terceira rodada sem novidade: nada convertido
    res3 = converter.convert(raw_dir, lake_dir)
    assert (res3.converted, res3.skipped) == (0, 4)
    assert _rows(rateio).height == 2 * n_rateio


def test_concurso_reemitido_substitui_apenas_o_proprio(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    lake_dir = tmp_path / "lake"
    lake_dir.mkdir()
    _detalhe(raw_dir, 3000, "20261101")
    _detalhe(raw_dir, 3001, "20261101")
    converter.convert(raw_dir, lake_dir)
    rateio = lake_dir / "loterias" / "rateio"
    antes = _rows(rateio).height

    novo = _detalhe(raw_dir, 3001, "20261105")
    data = json.loads(novo.read_text())
    data["listaRateioPremio"] = data["listaRateioPremio"][:1]
    novo.write_text(json.dumps(data), encoding="utf-8")
    res = converter.convert(raw_dir, lake_dir)
    assert not res.errors
    # so o 3001 e reescrito (rateio + ganhadores); o 3000 e pulado
    assert (res.converted, res.skipped) == (2, 2)

    df = _rows(rateio)
    assert df.filter(pl.col("concurso") == 3001).height == 1
    assert df.height == antes - (antes // 2) + 1


def test_json_invalido_e_erro_contado_e_nao_derruba_os_demais(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    lake_dir = tmp_path / "lake"
    lake_dir.mkdir()
    _detalhe(raw_dir, 3000, "20261101")
    ruim = raw_dir / "detalhe" / "megasena_3001@20261101.json"
    ruim.write_text("{nao e json", encoding="utf-8")

    res = converter.convert(raw_dir, lake_dir)
    assert len(res.errors) == 1
    assert "megasena_3001" in res.errors[0]
    assert res.converted == 2
    assert sorted(_rows(lake_dir / "loterias" / "rateio")["concurso"].unique()) == [
        3000
    ]
