"""Tests for loterias-fetcher lake conversion and check_dataset."""

from __future__ import annotations

import shutil
from pathlib import Path

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
