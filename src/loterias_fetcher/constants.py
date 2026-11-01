"""Constants and metadata for loterias-fetcher."""

from __future__ import annotations

from dataclasses import dataclass

PARAMS_URL = "https://loterias.caixa.gov.br/Style%20Library/json/params.txt"
DEFAULT_API_HOST = "https://servicebus3.caixa.gov.br/portaldeloterias"


@dataclass(frozen=True)
class ModalidadeInfo:
    slug: str
    download_name: str
    display_name: str
    since_year: int
    has_trevos: bool = False
    has_time_coracao: bool = False
    has_mes_sorte: bool = False
    is_dupla_sena: bool = False


MODALIDADES: dict[str, ModalidadeInfo] = {
    "megasena": ModalidadeInfo(
        slug="megasena",
        download_name="Mega-Sena",
        display_name="Mega-Sena",
        since_year=1996,
    ),
    "lotofacil": ModalidadeInfo(
        slug="lotofacil",
        download_name="Lotofácil",
        display_name="Lotofácil",
        since_year=2003,
    ),
    "quina": ModalidadeInfo(
        slug="quina",
        download_name="Quina",
        display_name="Quina",
        since_year=1994,
    ),
    "lotomania": ModalidadeInfo(
        slug="lotomania",
        download_name="Lotomania",
        display_name="Lotomania",
        since_year=1999,
    ),
    "timemania": ModalidadeInfo(
        slug="timemania",
        download_name="Timemania",
        display_name="Timemania",
        since_year=2008,
        has_time_coracao=True,
    ),
    "duplasena": ModalidadeInfo(
        slug="duplasena",
        download_name="Dupla Sena",
        display_name="Dupla Sena",
        since_year=2001,
        is_dupla_sena=True,
    ),
    "diadesorte": ModalidadeInfo(
        slug="diadesorte",
        download_name="Dia de Sorte",
        display_name="Dia de Sorte",
        since_year=2018,
        has_mes_sorte=True,
    ),
    "supersete": ModalidadeInfo(
        slug="supersete",
        download_name="Super 7",  # "Super Sete" retorna 404 na Caixa!
        display_name="Super Sete",
        since_year=2020,
    ),
    "maismilionaria": ModalidadeInfo(
        slug="maismilionaria",
        download_name="+Milionária",
        display_name="+Milionária",
        since_year=2022,
        has_trevos=True,
    ),
    "federal": ModalidadeInfo(
        slug="federal",
        download_name="Loteria Federal",
        display_name="Federal",
        since_year=1962,
    ),
    "loteca": ModalidadeInfo(
        slug="loteca",
        download_name="Loteca",
        display_name="Loteca",
        since_year=2002,
    ),
}
