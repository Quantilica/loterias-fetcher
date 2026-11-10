"""Tests for loterias-fetcher lake conversion and check_dataset."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

import polars as pl
import pytest
from quantilica.analytics.lake import check_dataset

from loterias_fetcher.constants import MODALIDADES
from loterias_fetcher.lake import converter

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_pl_read_excel = pl.read_excel


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


def _xlsx_com_celula_numerica_malformada(src: Path, dest: Path) -> None:
    """Copia ``src`` e acrescenta a coluna ``Arrecadacao Total`` com células
    numéricas (sem ``t="s"``) cujo conteúdo não é um float: o calamine falha com
    ``Parse float error: invalid float literal``."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                xml = data.decode("utf-8")
                xml = re.sub(
                    r'<dimension ref="A1:Y(\d+)"/>', r'<dimension ref="A1:Z\1"/>', xml
                )
                xml = xml.replace(
                    '</row><row r="2"',
                    '<c r="Z1" t="inlineStr"><is><t>Arrecadacao Total</t></is></c>'
                    '</row><row r="2"',
                    1,
                )
                xml = xml.replace(
                    '</row><row r="3"',
                    '<c r="Z2"><v>1.234,56</v></c></row><row r="3"',
                    1,
                )
                xml = xml.replace(
                    '</row><row r="4"', '<c r="Z3"><v></v></c></row><row r="4"', 1
                )
                data = xml.encode("utf-8")
            zout.writestr(item, data)


def test_xlsx_com_celula_numerica_malformada_nao_perde_linhas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir = tmp_path / "raw"
    concursos_raw = raw_dir / "concursos"
    concursos_raw.mkdir(parents=True)
    dest = concursos_raw / "lotomania@20261104.xlsx"
    _xlsx_com_celula_numerica_malformada(FIXTURES_DIR / "lotomania.xlsx", dest)

    # O calamine antigo falha neste arquivo; o atual é tolerante. Simula a falha.
    def _calamine_falha(*_a, **_k):
        raise RuntimeError(
            "calamine error: Xlsx error: Parse float error: invalid float literal"
        )

    monkeypatch.setattr(pl, "read_excel", _calamine_falha)
    res = converter.convert(raw_dir, tmp_path / "lake")
    assert not res.errors, res.errors
    n_ref = _pl_read_excel(FIXTURES_DIR / "lotomania.xlsx").height
    rows = _rows(tmp_path / "lake" / "loterias" / "concursos")
    assert rows.height == n_ref  # nenhuma linha perdida
    by_concurso = {r["concurso"]: r for r in rows.iter_rows(named=True)}
    assert by_concurso[1001]["arrecadacao_total"] == 1234.56  # "1.234,56" lido como BR
    assert by_concurso[1002]["arrecadacao_total"] is None  # vazio -> nulo


def test_leitura_como_texto_preserva_celulas_e_cabecalho(tmp_path: Path) -> None:
    from loterias_fetcher.lake import read_xlsx_as_text

    dest = tmp_path / "x.xlsx"
    _xlsx_com_celula_numerica_malformada(FIXTURES_DIR / "lotomania.xlsx", dest)
    df = read_xlsx_as_text(dest)
    ref = _pl_read_excel(FIXTURES_DIR / "lotomania.xlsx")
    assert df.height == ref.height
    assert df["Concurso"].to_list() == [str(v) for v in ref["Concurso"]]
    assert df["Bola1"][0] == "01"  # texto preservado (zero à esquerda)
    assert df["Arrecadacao Total"].to_list()[:2] == ["1.234,56", None]


def _xlsx_sem_atributo_r(dest: Path) -> None:
    """XLSX minimo no estilo da Caixa: prefixo ``x:`` e celulas sem o atributo ``r``."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    def row(vals: list[str], tipo: str = "n") -> str:
        cells = "".join(f'<x:c t="{tipo}"><x:v>{v}</x:v></x:c>' for v in vals)
        return f"<x:row>{cells}</x:row>"

    header = row(["Concurso", "Data Sorteio", "Bola1", "Bola2"], "str")
    body = row(["1", "02/10/1999", "01", "02"]) + row(["2", "09/10/1999", "03", "04"])
    sheet = (
        f'<x:worksheet xmlns:x="{ns}"><x:sheetData>{header}{body}</x:sheetData>'
        "</x:worksheet>"
    )
    wb = (
        f'<x:workbook xmlns:x="{ns}" xmlns:r="{rel_ns}"><x:sheets>'
        '<x:sheet name="P" sheetId="1" r:id="rId1"/></x:sheets></x:workbook>'
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships"><Relationship Id="rId1" Type="worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    with zipfile.ZipFile(dest, "w") as z:
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


def test_leitura_como_texto_sem_atributo_r_usa_a_posicao(tmp_path: Path) -> None:
    from loterias_fetcher.lake import read_xlsx_as_text

    dest = tmp_path / "sem_r.xlsx"
    _xlsx_sem_atributo_r(dest)
    df = read_xlsx_as_text(dest)
    assert df.columns == ["Concurso", "Data Sorteio", "Bola1", "Bola2"]
    assert df.height == 2
    assert df["Concurso"].to_list() == ["1", "2"]
    assert df["Bola1"].to_list() == ["01", "03"]
    assert df["Bola2"].to_list() == ["02", "04"]


def test_leitura_sem_atributo_r_avisa_linha_com_outro_numero_de_celulas(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from loterias_fetcher.lake import read_xlsx_as_text

    dest = tmp_path / "sem_r.xlsx"
    _xlsx_sem_atributo_r(dest)
    with zipfile.ZipFile(dest) as z:
        files = {n: z.read(n) for n in z.namelist()}
    sheet = files["xl/worksheets/sheet1.xml"].decode()
    curta = '<x:row><x:c t="n"><x:v>3</x:v></x:c><x:c t="n"><x:v>x</x:v></x:c></x:row>'
    outra = '<x:row><x:c t="n"><x:v>4</x:v></x:c></x:row>'
    files["xl/worksheets/sheet1.xml"] = sheet.replace(
        "</x:sheetData>", curta + outra + "</x:sheetData>"
    ).encode()
    with zipfile.ZipFile(dest, "w") as z:
        for n, b in files.items():
            z.writestr(n, b)
    with caplog.at_level("WARNING", logger="loterias_fetcher.lake"):
        df = read_xlsx_as_text(dest)
    avisos = [r for r in caplog.records if "sem atributo r" in r.getMessage()]
    assert len(avisos) == 1  # uma vez por arquivo
    assert "linha 4 " in avisos[0].getMessage()
    assert df.height == 4  # o resultado nao muda


def test_leitura_sem_atributo_r_consistente_nao_avisa(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from loterias_fetcher.lake import read_xlsx_as_text

    dest = tmp_path / "sem_r.xlsx"
    _xlsx_sem_atributo_r(dest)
    with caplog.at_level("WARNING", logger="loterias_fetcher.lake"):
        read_xlsx_as_text(dest)
    assert not [r for r in caplog.records if "sem atributo r" in r.getMessage()]
