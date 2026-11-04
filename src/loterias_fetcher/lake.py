"""Universal Hive Parquet Lake converter for loterias-fetcher."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

try:
    import polars as pl
    from quantilica.analytics.lake import ConvertResult, LakeWriter
    from quantilica.core.lake import (
        DatasetDescriptor,
        file_key,
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


def parse_xlsx_concursos(file_path: Path, modalidade: str) -> pl.DataFrame:
    """Parse a Caixa XLSX file into standardized concursos records."""
    df_raw = pl.read_excel(file_path)
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
                    mod_slug = file_key(raw_file).lower()
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
                base_part = file_key(jf)
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
