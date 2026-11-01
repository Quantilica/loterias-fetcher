"""Dataset catalog for loterias-fetcher."""

from __future__ import annotations

from typing import Any

from .constants import DEFAULT_API_HOST, MODALIDADES

__all__ = [
    "GROUPS",
    "GROUP_ALIASES",
    "list_datasets",
]

CONCURSOS_ENTRIES: list[dict[str, Any]] = [
    {
        "id": slug,
        "base_id": slug,
        "name": f"Resultados Históricos — {mod.display_name}",
        "url": (
            f"{DEFAULT_API_HOST}/api/resultados/download?modalidade={mod.download_name}"
        ),
        "ext": "xlsx",
        "group": "concursos",
        "modalidade": slug,
    }
    for slug, mod in MODALIDADES.items()
]

DETALHE_ENTRIES: list[dict[str, Any]] = [
    {
        "id": f"{slug}_ultimo",
        "base_id": slug,
        "name": f"Último Concurso — {mod.display_name}",
        "url": f"{DEFAULT_API_HOST}/api/{slug}",
        "ext": "json",
        "group": "detalhe",
        "modalidade": slug,
    }
    for slug, mod in MODALIDADES.items()
]

GROUPS: dict[str, dict[str, Any]] = {
    "concursos": {
        "name": "Resultados Consolidados (XLSX)",
        "entries": CONCURSOS_ENTRIES,
    },
    "detalhe": {
        "name": "Detalhes de Concursos (JSON)",
        "entries": DETALHE_ENTRIES,
    },
}

GROUP_ALIASES: dict[str, str] = {
    "resultados": "concursos",
    "historico": "concursos",
    "xlsx": "concursos",
    "json": "detalhe",
}


def list_datasets(group: str | None = None) -> list[dict[str, Any]]:
    """List datasets for a group or all groups."""
    if group is None:
        entries: list[dict[str, Any]] = []
        for g_data in GROUPS.values():
            entries.extend(g_data["entries"])
        return entries

    canon = GROUP_ALIASES.get(group, group)
    if canon not in GROUPS:
        raise ValueError(f"Grupo desconhecido: {group!r}")
    return list(GROUPS[canon]["entries"])
