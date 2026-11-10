"""Universal Hive Parquet Lake converter for loterias-fetcher."""

from __future__ import annotations

import json
import logging
import posixpath
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:
    import polars as pl
    from quantilica.analytics.lake import ConvertResult, LakeWriter
    from quantilica.core.lake import (
        DatasetDescriptor,
        composite_file_key,
        partition_types_for,
        select_current,
    )
except ImportError as exc:
    raise ImportError(
        "loterias_fetcher.lake requer o extra 'analysis': "
        "uv add 'loterias-fetcher[analysis]' "
        "--index https://index.quantilica.com/simple/"
    ) from exc

from loterias_fetcher.constants import MODALIDADES

logger = logging.getLogger(__name__)

SOURCE_ID = "loterias"
DATASETS = ["concursos", "rateio", "ganhadores_municipio"]


RATEIO_SCHEMA: dict[str, Any] = {
    "modalidade": pl.Utf8,
    "concurso": pl.Int64,
    "faixa": pl.Int64,
    "descricao_faixa": pl.Utf8,
    "ganhadores": pl.Int64,
    "valor_premio": pl.Float64,
}
GANHADORES_SCHEMA: dict[str, Any] = {
    "modalidade": pl.Utf8,
    "concurso": pl.Int64,
    "posicao": pl.Int64,
    "municipio": pl.Utf8,
    "uf": pl.Utf8,
    "ganhadores": pl.Int64,
}


def _clean_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _norm_col(col_name: str) -> str:
    s = unicodedata.normalize("NFKD", col_name)
    s = s.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref)
    n = 0
    for ch in letters.group(0) if letters else "A":
        n = n * 26 + ord(ch) - 64
    return n - 1


def _si_text(si: ET.Element) -> str:
    """Texto de um item de sharedStrings (ignora a fonetica ``rPh``)."""
    return "".join(t.text or "" for t in si.iter(f"{_NS}t") if not _in_phonetic(si, t))


def _in_phonetic(si: ET.Element, t: ET.Element) -> bool:
    return any(t in list(ph.iter(f"{_NS}t")) for ph in si.iter(f"{_NS}rPh"))


def _first_sheet_path(zf: zipfile.ZipFile) -> str:
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    sheet = wb.find(f"{_NS}sheets/{_NS}sheet")
    if sheet is None:
        raise ValueError("XLSX sem planilhas")
    rid = sheet.get(_DOC_REL)
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.iter(f"{_REL_NS}Relationship"):
        if rel.get("Id") == rid:
            target = rel.get("Target") or ""
            return (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath(posixpath.join("xl", target))
            )
    raise ValueError("XLSX: planilha sem relacionamento")


def read_xlsx_as_text(file_path: Path) -> pl.DataFrame:
    """Le a primeira planilha de um XLSX com todas as celulas como texto.

    Alternativa ao ``pl.read_excel`` para quando o calamine rejeita o arquivo (por
    exemplo, celula numerica com ``1.234,56`` ou conteudo nao numerico: ``Parse
    float error: invalid float literal``). O conteudo da celula vai como esta no
    XML, sem converter nada; a regra de conversao fica em ``parse_xlsx_concursos``.
    Com o atributo ``r`` a coluna vem dele (celulas vazias omitidas); sem ele, a
    coluna e a posicao da celula na linha (assim sao as planilhas da Caixa).
    A primeira linha e o cabecalho; nenhuma linha de dados e descartada.
    """
    with zipfile.ZipFile(file_path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            shared = [_si_text(si) for si in root.iter(f"{_NS}si")]
        rows: list[dict[int, str | None]] = []
        header_len: int | None = None
        warned = False
        with zf.open(_first_sheet_path(zf)) as fh:
            for _, el in ET.iterparse(fh):
                if el.tag != f"{_NS}row":
                    continue
                cells: dict[int, str | None] = {}
                pos = 0  # coluna da proxima celula quando faltar o atributo r
                sem_r = False
                n_cells = 0
                for c in el.findall(f"{_NS}c"):
                    ref = c.get("r")
                    n_cells += 1
                    sem_r = sem_r or not ref
                    col = _col_index(ref) if ref else pos
                    pos = col + 1
                    kind = c.get("t")
                    v = c.find(f"{_NS}v")
                    if kind == "inlineStr":
                        is_ = c.find(f"{_NS}is")
                        val: str | None = _si_text(is_) if is_ is not None else None
                    elif v is None or v.text is None:
                        val = None
                    elif kind == "s":
                        val = shared[int(v.text)]
                    else:
                        val = v.text
                    cells[col] = val
                if header_len is None:
                    header_len = n_cells
                elif sem_r and n_cells != header_len and not warned:
                    # sem o atributo r nao ha como saber qual celula faltou
                    warned = True
                    logger.warning(
                        "LOTERIAS %s: linha %d sem atributo r tem %d celulas e o "
                        "cabecalho tem %d; colunas lidas pela posicao",
                        file_path.name,
                        len(rows) + 1,
                        n_cells,
                        header_len,
                    )
                rows.append(cells)
                el.clear()
    if not rows:
        return pl.DataFrame()
    width = max((max(r) + 1 for r in rows if r), default=0)
    header = [(rows[0].get(i) or "").strip() or f"column_{i + 1}" for i in range(width)]
    seen: dict[str, int] = {}
    names = []
    for h in header:
        seen[h] = seen.get(h, 0) + 1
        names.append(h if seen[h] == 1 else f"{h}_{seen[h]}")
    data = {n: [r.get(i) for r in rows[1:]] for i, n in enumerate(names)}
    # descarta coluna sem nome no cabecalho e sem nenhum valor (sobra do fallback)
    for i, n in enumerate(names):
        if not (rows[0].get(i) or "").strip() and all(v is None for v in data[n]):
            del data[n]
    return pl.DataFrame(data, schema={n: pl.Utf8 for n in data})


def _read_excel_tolerant(file_path: Path) -> pl.DataFrame:
    """``pl.read_excel`` e, se o calamine rejeitar o arquivo, leitura como texto."""
    try:
        return pl.read_excel(file_path)
    except Exception as exc:
        logger.warning(
            "LOTERIAS %s: leitura padrao falhou (%s); relendo como texto",
            file_path.name,
            exc,
        )
        try:
            return read_xlsx_as_text(file_path)
        except Exception as fallback_exc:
            raise exc from fallback_exc


def parse_xlsx_concursos(file_path: Path, modalidade: str) -> pl.DataFrame:
    """Parse a Caixa XLSX file into standardized concursos records."""
    df_raw = _read_excel_tolerant(file_path)
    if df_raw.height == 0:
        return pl.DataFrame(
            schema={
                "modalidade": pl.Utf8,
                "concurso": pl.Int64,
                "data_sorteio": pl.Utf8,
                "dezenas": pl.Utf8,
                "arrecadacao_total": pl.Float64,
                "acumulado": pl.Boolean,
                "valor_acumulado": pl.Float64,
                "estimativa_premio": pl.Float64,
            }
        )

    cols_map = {_norm_col(c): c for c in df_raw.columns}

    # Find concurso col
    concurso_col = next((cols_map[c] for c in cols_map if c == "concurso"), None)
    if concurso_col is None:
        concurso_col = df_raw.columns[0]

    # Find data col
    data_col = next(
        (cols_map[c] for c in cols_map if "data" in c and "sorteio" in c),
        next((cols_map[c] for c in cols_map if "data" in c), None),
    )

    # Find dezenas / bolas / colunas
    dezena_prefixes = ("bola_", "bola", "coluna_", "dezena_")
    dezena_cols = [
        cols_map[c] for c in cols_map if any(c.startswith(p) for p in dezena_prefixes)
    ]
    if not dezena_cols:
        # Fallback for columns like '1', '2', etc.
        dezena_cols = [
            c
            for c in df_raw.columns
            if re.match(r"^(?:bola|coluna)?\s*\d+$", c.strip(), re.I)
        ]

    # Arrecadação
    arrecadacao_col = next(
        (cols_map[c] for c in cols_map if "arrecadacao" in c),
        None,
    )

    # Acumulado
    acumulado_col = next(
        (
            cols_map[c]
            for c in cols_map
            if c.startswith("acumulado") and "especial" not in c
        ),
        None,
    )

    # Valor acumulado próximo
    val_acumulado_col = next(
        (
            cols_map[c]
            for c in cols_map
            if "valor_acumulado" in c or "acumulado_proximo" in c
        ),
        None,
    )

    # Estimativa
    estimativa_col = next(
        (cols_map[c] for c in cols_map if "estimativa" in c),
        None,
    )

    rows = []
    for row in df_raw.iter_rows(named=True):
        c_val = row.get(concurso_col)
        if c_val is None or str(c_val).strip() == "":
            continue
        try:
            concurso_num = int(float(str(c_val).replace(".", "").replace(",", ".")))
        except (ValueError, TypeError):
            continue

        d_val = _clean_str(row.get(data_col) if data_col else "")
        dezenas = []
        for dcol in dezena_cols:
            v = row.get(dcol)
            if v is not None and str(v).strip() != "":
                dezenas.append(str(v).strip().zfill(2))
        dezenas_str = ", ".join(dezenas)

        def _to_float(v: Any) -> float | None:
            if v is None:
                return None
            s = str(v).strip()
            if not s or s == "-":
                return None
            s = s.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
            try:
                return float(s)
            except ValueError:
                return None

        def _to_bool(v: Any) -> bool:
            if v is None:
                return False
            s = str(v).strip().lower()
            return s in ("sim", "true", "1", "s")

        arr_val = _to_float(row.get(arrecadacao_col)) if arrecadacao_col else None
        acum_val = _to_bool(row.get(acumulado_col)) if acumulado_col else False
        v_acum = _to_float(row.get(val_acumulado_col)) if val_acumulado_col else None
        est_premio = _to_float(row.get(estimativa_col)) if estimativa_col else None

        rows.append(
            {
                "modalidade": modalidade,
                "concurso": concurso_num,
                "data_sorteio": d_val,
                "dezenas": dezenas_str,
                "arrecadacao_total": arr_val,
                "acumulado": acum_val,
                "valor_acumulado": v_acum,
                "estimativa_premio": est_premio,
            }
        )

    if not rows:
        return pl.DataFrame(
            schema={
                "modalidade": pl.Utf8,
                "concurso": pl.Int64,
                "data_sorteio": pl.Utf8,
                "dezenas": pl.Utf8,
                "arrecadacao_total": pl.Float64,
                "acumulado": pl.Boolean,
                "valor_acumulado": pl.Float64,
                "estimativa_premio": pl.Float64,
            }
        )

    return pl.DataFrame(rows)


def parse_json_detalhe(
    file_path: Path, modalidade: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse a contest detail JSON file into rateio and ganhadores records.

    Raises ``ValueError``/``OSError`` for an unreadable file, a JSON that is not an
    object or one without the contest number: the converter counts these as errors
    instead of treating the file as empty.
    """
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"{file_path.name}: JSON nao e um objeto")

    concurso = data.get("numero") or data.get("concurso")
    if concurso is None:
        raise ValueError(f"{file_path.name}: sem numero do concurso")

    rateio_rows: list[dict[str, Any]] = []
    lista_rateio = data.get("listaRateioPremio") or []
    for item in lista_rateio:
        if not isinstance(item, dict):
            continue
        rateio_rows.append(
            {
                "modalidade": modalidade,
                "concurso": int(concurso),
                "faixa": int(item.get("faixa") or item.get("ordem") or 0),
                "descricao_faixa": str(item.get("descricaoFaixa") or ""),
                "ganhadores": int(item.get("numeroDeGanhadores") or 0),
                "valor_premio": float(item.get("valorPremio") or 0.0),
            }
        )

    ganhadores_rows: list[dict[str, Any]] = []
    lista_ganhadores = data.get("listaMunicipioUFGanhadores") or []
    for item in lista_ganhadores:
        if not isinstance(item, dict):
            continue
        num_g = item.get("ganhadores") or item.get("numeroDeGanhadores") or 0
        ganhadores_rows.append(
            {
                "modalidade": modalidade,
                "concurso": int(concurso),
                "posicao": item.get("posicao"),
                "municipio": str(item.get("municipio") or "").strip(),
                "uf": str(item.get("uf") or "").strip().upper(),
                "ganhadores": int(num_g),
            }
        )

    return rateio_rows, ganhadores_rows


class LoteriasLakeConverter:
    """Universal Hive Lake converter for loterias-fetcher."""

    source_id = SOURCE_ID

    def datasets(self) -> list[str]:
        return list(DATASETS)

    def convert(
        self,
        input_dir: Path,
        lake_dir: Path,
        *,
        datasets: list[str] | None = None,
        force: bool = False,
    ) -> ConvertResult:
        res = ConvertResult()
        target_datasets = set(datasets or DATASETS)

        # 1. Dataset 'concursos' from raw XLSX files
        if "concursos" in target_datasets:
            writer_concursos = LakeWriter(
                lake_dir / SOURCE_ID / "concursos",
                DatasetDescriptor(
                    source_id=SOURCE_ID,
                    dataset_id="concursos",
                    alias="concursos",
                    partition_keys=["modalidade"],
                    partition_types=partition_types_for(["modalidade"]),
                ),
                force=force,
            )
            concursos_dir = input_dir / "concursos"
            if concursos_dir.is_dir():
                xlsx_files = list(concursos_dir.glob("*.xlsx"))
                current_files = select_current(xlsx_files)
                for raw_file in current_files:
                    # Stem is like 'megasena@20261101'
                    mod_slug = composite_file_key(raw_file).lower()
                    if mod_slug not in MODALIDADES:
                        continue
                    try:
                        if not force and writer_concursos.is_current(
                            raw_file, partitions={"modalidade": mod_slug}
                        ):
                            res.skipped += 1
                            continue

                        df = parse_xlsx_concursos(raw_file, mod_slug)
                        writer_concursos.write_polars(
                            df,
                            raw_file,
                            partitions={"modalidade": mod_slug},
                        )
                        res.converted += 1
                    except Exception as exc:
                        res.errors.append(f"Erro em concursos {raw_file.name}: {exc}")

        # 2. Datasets 'rateio' and 'ganhadores_municipio' from JSON files
        detalhe_dir = input_dir / "detalhe"
        has_detail_targets = (
            "rateio" in target_datasets or "ganhadores_municipio" in target_datasets
        )
        if has_detail_targets and detalhe_dir.is_dir():
            writer_rateio = LakeWriter(
                lake_dir / SOURCE_ID / "rateio",
                DatasetDescriptor(
                    source_id=SOURCE_ID,
                    dataset_id="rateio",
                    alias="rateio",
                    partition_keys=["modalidade"],
                    partition_types=partition_types_for(["modalidade"]),
                ),
                force=force,
            )
            writer_ganhadores = LakeWriter(
                lake_dir / SOURCE_ID / "ganhadores_municipio",
                DatasetDescriptor(
                    source_id=SOURCE_ID,
                    dataset_id="ganhadores_municipio",
                    alias="ganhadores_municipio",
                    partition_keys=["modalidade"],
                    partition_types=partition_types_for(["modalidade"]),
                ),
                force=force,
            )

            # Group JSON files by modalidade
            json_files = select_current(list(detalhe_dir.glob("*.json")))
            files_by_mod: dict[str, list[Path]] = {}
            for jf in json_files:
                # Format: {mod}_{concurso}@{stamp}.json
                base_part = composite_file_key(jf)
                mod = base_part.split("_")[0].lower()
                files_by_mod.setdefault(mod, []).append(jf)

            # Um concurso = um arquivo de origem = um membro do arquivo agrupado
            # ``<modalidade>.parquet`` da particao. Escrever a modalidade inteira com
            # o primeiro JSON como ``src`` (como era) fazia a reconversao apos um
            # concurso novo ser pulada por sha256 e perdia as demais linhas.
            for mod_slug, files in files_by_mod.items():
                if mod_slug not in MODALIDADES:
                    continue
                partitions = {"modalidade": mod_slug}
                targets = (
                    ("rateio", writer_rateio, RATEIO_SCHEMA, 0),
                    ("ganhadores_municipio", writer_ganhadores, GANHADORES_SCHEMA, 1),
                )
                for jf in sorted(files):
                    pending = [
                        t
                        for t in targets
                        if t[0] in target_datasets
                        and not self._member_current(t[1], jf, mod_slug, res)
                    ]
                    if not pending:
                        continue
                    try:
                        parsed = parse_json_detalhe(jf, mod_slug)
                    except Exception as exc:
                        res.errors.append(f"Erro em detalhe {jf.name}: {exc}")
                        continue
                    for ds_name, writer, schema, idx in pending:
                        rows = parsed[idx]
                        if not rows:
                            continue
                        try:
                            written = writer.write_member(
                                pl.DataFrame(rows, schema=schema, strict=False),
                                jf,
                                group_key=mod_slug,
                                partitions=partitions,
                            )
                        except Exception as exc:
                            res.errors.append(f"Erro em {ds_name} {jf.name}: {exc}")
                            continue
                        if written.status == "skipped":
                            res.skipped += 1
                        else:
                            res.converted += 1

        return res

    @staticmethod
    def _member_current(
        writer: LakeWriter, jf: Path, mod_slug: str, res: ConvertResult
    ) -> bool:
        """Conta ``skipped`` quando o JSON ja e membro do agrupado com o mesmo sha."""
        if writer.is_current_member(
            jf, group_key=mod_slug, partitions={"modalidade": mod_slug}
        ):
            res.skipped += 1
            return True
        return False


converter = LoteriasLakeConverter()
