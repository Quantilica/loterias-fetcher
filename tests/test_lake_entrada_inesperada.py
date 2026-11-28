"""Conversor do lake: entrada inesperada é erro do arquivo, não dado errado."""

from __future__ import annotations

import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from loterias_fetcher import lake
from loterias_fetcher.lake import converter, parse_json_detalhe

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _xlsx(dest: Path, header: list[str], rows: list[list[str]]) -> Path:
    """XLSX sintético mínimo (texto em linha) com cabeçalho e linhas dadas."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    def row(vals: list[str]) -> str:
        cells = "".join(
            f'<c t="inlineStr"><is><t>{v}</t></is></c>' if v != "" else "<c/>"
            for v in vals
        )
        return f"<row>{cells}</row>"

    sheet = (
        f'<worksheet xmlns="{ns}"><sheetData>'
        + row(header)
        + "".join(row(r) for r in rows)
        + "</sheetData></worksheet>"
    )
    wb = (
        f'<workbook xmlns="{ns}" xmlns:r="{rel_ns}"><sheets>'
        '<sheet name="P" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships"><Relationship Id="rId1" Type="worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w") as z:
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return dest


def _concursos(raw: Path, header: list[str], rows: list[list[str]]) -> None:
    _xlsx(raw / "concursos" / "megasena@20261101.xlsx", header, rows)


def _parquets(lake_dir: Path, dataset: str) -> pl.DataFrame:
    parts = sorted((lake_dir / "loterias" / dataset).rglob("*.parquet"))
    return pl.concat([pl.read_parquet(p) for p in parts], how="diagonal")


HEADER = ["Concurso", "Data do Sorteio", "Bola1", "Bola2"]


def test_xlsx_valido_sintetico_converte(tmp_path: Path) -> None:
    raw, lk = tmp_path / "raw", tmp_path / "lake"
    _concursos(raw, HEADER, [["1", "01/01/2026", "1", "2"]])
    res = converter.convert(raw, lk, datasets=["concursos"])
    assert res.errors == [] and res.converted == 1
    assert _parquets(lk, "concursos")["dezenas"].to_list() == ["01, 02"]


def test_coluna_concurso_renomeada_e_erro_e_nao_grava(tmp_path: Path) -> None:
    raw, lk = tmp_path / "raw", tmp_path / "lake"
    _concursos(
        raw,
        ["Numero Sorteio", "Data do Sorteio", "Bola1", "Bola2"],
        [["1", "01/01/2026", "1", "2"]],
    )
    res = converter.convert(raw, lk, datasets=["concursos"])
    assert res.converted == 0
    assert len(res.errors) == 1
    assert "megasena@20261101.xlsx" in res.errors[0]
    assert "Concurso" in res.errors[0]
    assert "Numero Sorteio" in res.errors[0]  # lista as colunas encontradas
    assert not list(lk.rglob("*.parquet"))


def test_sem_colunas_das_bolas_e_erro_e_nao_grava_dezenas_vazias(
    tmp_path: Path,
) -> None:
    raw, lk = tmp_path / "raw", tmp_path / "lake"
    _concursos(
        raw,
        ["Concurso", "Data do Sorteio", "Numeros"],
        [["1", "01/01/2026", "01 02"]],
    )
    res = converter.convert(raw, lk, datasets=["concursos"])
    assert res.converted == 0
    assert len(res.errors) == 1
    assert "bolas" in res.errors[0] and "Numeros" in res.errors[0]
    assert not list(lk.rglob("*.parquet"))


def test_federal_com_extracao_e_sem_bolas_converte_com_dezenas_vazias(
    tmp_path: Path,
) -> None:
    """A Federal publica ``Extração`` e bilhetes nas colunas de prêmio."""
    raw, lk = tmp_path / "raw", tmp_path / "lake"
    _xlsx(
        raw / "concursos" / "federal@20261101.xlsx",
        ["Extração", "Data do Sorteio", "1º Prêmio", "2º Prêmio"],
        [["6100", "01/11/2026", "123456", "654321"]],
    )
    res = converter.convert(raw, lk, datasets=["concursos"])
    assert res.errors == [] and res.converted == 1
    df = _parquets(lk, "concursos")
    assert df["concurso"].to_list() == [6100] and df["dezenas"].to_list() == [""]


def test_erro_de_um_arquivo_nao_derruba_os_demais(tmp_path: Path) -> None:
    raw, lk = tmp_path / "raw", tmp_path / "lake"
    shutil.copy2(
        FIXTURES_DIR / "quina.xlsx", _mk(raw / "concursos") / "quina@20261101.xlsx"
    )
    _concursos(raw, ["Sorteio", "Bola1"], [["1", "2"]])
    res = converter.convert(raw, lk, datasets=["concursos"])
    assert res.converted == 1
    assert len(res.errors) == 1 and "megasena" in res.errors[0]


def _mk(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_poucas_linhas_ilegiveis_sao_contadas_em_aviso(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    raw, lk = tmp_path / "raw", tmp_path / "lake"
    rows = [[str(i), "01/01/2026", "1", "2"] for i in range(1, 200)]
    rows.append(["abc", "01/01/2026", "3", "4"])  # 1 em 200 = 0,5%
    _concursos(raw, HEADER, rows)
    with caplog.at_level(logging.WARNING):
        res = converter.convert(raw, lk, datasets=["concursos"])
    assert res.errors == [] and res.converted == 1
    assert _parquets(lk, "concursos").height == 199
    assert "1 de 200 linhas descartadas" in caplog.text
    assert "'abc'" in caplog.text


def test_muitas_linhas_ilegiveis_e_erro_do_arquivo(tmp_path: Path) -> None:
    raw, lk = tmp_path / "raw", tmp_path / "lake"
    rows = [[str(i), "01/01/2026", "1", "2"] for i in range(1, 9)]
    rows += [["x", "01/01/2026", "3", "4"], ["y", "01/01/2026", "3", "4"]]
    _concursos(raw, HEADER, rows)
    res = converter.convert(raw, lk, datasets=["concursos"])
    assert res.converted == 0
    assert len(res.errors) == 1
    assert "2 de 10 linhas" in res.errors[0]
    assert not list(lk.rglob("*.parquet"))


def test_linha_totalmente_vazia_nao_conta_como_descarte(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    raw, lk = tmp_path / "raw", tmp_path / "lake"
    rows = [["1", "01/01/2026", "1", "2"], ["", "", "", ""]]
    _concursos(raw, HEADER, rows)
    with caplog.at_level(logging.WARNING):
        res = converter.convert(raw, lk, datasets=["concursos"])
    assert res.errors == [] and res.converted == 1
    assert "descartadas" not in caplog.text


def test_linha_com_dados_e_sem_concurso_conta_como_descarte(tmp_path: Path) -> None:
    discarded: list[str] = []
    xlsx = _xlsx(
        tmp_path / "megasena@20261101.xlsx",
        HEADER,
        [["1", "01/01/2026", "1", "2"], ["", "02/01/2026", "3", "4"]],
    )
    df = lake.parse_xlsx_concursos(xlsx, "megasena", discarded=discarded)
    assert df.height == 1
    assert discarded == ["linha 3: concurso vazio"]


# --- JSON de detalhe: ausência é nulo, não zero --------------------------------


def _json(tmp: Path, payload: dict[str, Any]) -> Path:
    p = tmp / "megasena_3000@20261101.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_detalhe_ausencia_vira_nulo_e_zero_continua_zero(tmp_path: Path) -> None:
    payload = {
        "numero": 3000,
        "listaRateioPremio": [
            {"faixa": 1, "descricaoFaixa": "6 acertos"},  # sem ganhadores e prêmio
            {
                "faixa": 2,
                "descricaoFaixa": "5 acertos",
                "numeroDeGanhadores": 0,
                "valorPremio": 0.0,
            },
            {
                "descricaoFaixa": "sem faixa",
                "numeroDeGanhadores": 3,
                "valorPremio": 9.5,
            },
        ],
        "listaMunicipioUFGanhadores": [
            {"posicao": 1, "municipio": " Rio ", "uf": "rj"},  # sem ganhadores
            {"posicao": 2, "municipio": "Sao Paulo", "uf": "sp", "ganhadores": 0},
        ],
    }
    rateio, ganh = parse_json_detalhe(_json(tmp_path, payload), "megasena")
    assert rateio[0]["ganhadores"] is None and rateio[0]["valor_premio"] is None
    assert rateio[1]["ganhadores"] == 0 and rateio[1]["valor_premio"] == 0.0
    assert rateio[2]["faixa"] is None
    assert ganh[0]["ganhadores"] is None
    assert ganh[0]["municipio"] == "Rio" and ganh[0]["uf"] == "RJ"
    assert ganh[1]["ganhadores"] == 0


def test_detalhe_com_nulos_chega_ao_parquet_como_nulo(tmp_path: Path) -> None:
    raw, lk = tmp_path / "raw", tmp_path / "lake"
    _json(
        _mk(raw / "detalhe"),
        {
            "numero": 3000,
            "listaRateioPremio": [{"faixa": 1}],
            "listaMunicipioUFGanhadores": [
                {"posicao": 1, "municipio": "X", "uf": "SP"}
            ],
        },
    )
    res = converter.convert(raw, lk, datasets=["rateio", "ganhadores_municipio"])
    assert res.errors == []
    rateio = _parquets(lk, "rateio")
    assert rateio["ganhadores"].to_list() == [None]
    assert rateio["valor_premio"].to_list() == [None]
    assert _parquets(lk, "ganhadores_municipio")["ganhadores"].to_list() == [None]


# --- entrada ausente ---------------------------------------------------------


def test_diretorio_de_entrada_inexistente_e_erro(tmp_path: Path) -> None:
    res = converter.convert(tmp_path / "nao-existe", tmp_path / "lake")
    assert res.converted == 0
    assert len(res.errors) == 1 and "nao-existe" in res.errors[0]


def test_dataset_pedido_sem_o_subdiretorio_e_erro(tmp_path: Path) -> None:
    raw = _mk(tmp_path / "raw")
    res = converter.convert(raw, tmp_path / "lake", datasets=["concursos"])
    assert len(res.errors) == 1 and "concursos" in res.errors[0]
    res = converter.convert(raw, tmp_path / "lake", datasets=["rateio"])
    assert len(res.errors) == 1 and "detalhe" in res.errors[0]


def test_acervo_sem_nenhum_subdiretorio_e_erro(tmp_path: Path) -> None:
    raw = _mk(tmp_path / "raw")
    res = converter.convert(raw, tmp_path / "lake")
    assert len(res.errors) == 2


def test_acervo_so_com_concursos_converte_sem_erro(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _concursos(raw, HEADER, [["1", "01/01/2026", "1", "2"]])
    res = converter.convert(raw, tmp_path / "lake")
    assert res.errors == [] and res.converted == 1


def test_manifesto_lateral_e_ignorado_em_silencio(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    raw, lk = tmp_path / "raw", tmp_path / "lake"
    jf = _json(
        _mk(raw / "detalhe"),
        {"numero": 3000, "listaRateioPremio": [{"faixa": 1, "valorPremio": 1.5}]},
    )
    jf = jf.rename(jf.with_name("megasena@20261101.json"))
    Path(f"{jf}.manifest.json").write_text("{}", encoding="utf-8")
    xlsx = _xlsx(
        raw / "concursos" / "megasena@20261101.xlsx",
        HEADER,
        [["1", "01/01/2026", "1", "2"]],
    )
    Path(f"{xlsx}.manifest.json").write_text("{}", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        res = converter.convert(raw, lk)
    assert res.errors == []
    assert "desconhecida" not in caplog.text
    assert res.converted == 3  # concursos + rateio + ganhadores_municipio
    assert _parquets(lk, "rateio").height == 1
