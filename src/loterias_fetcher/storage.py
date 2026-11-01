"""File location management for loterias-fetcher."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from quantilica.core.storage import (
    BaseDataRepository,
    build_stamped_filename,
    stamp_filename,
)


class DataRepository(BaseDataRepository):
    """Manages local storage for loterias-fetcher files."""

    def __init__(self, root: Path | str) -> None:
        super().__init__(root)

    def path_for_entry(
        self,
        entry: dict[str, Any],
        *,
        last_modified: dt.date | None = None,
    ) -> Path:
        """Compute the local path for a dataset entry."""
        group = entry.get("group", "concursos")
        ext = entry.get("ext", "xlsx")
        base_id = entry.get("base_id", entry.get("id", "loterias"))
        contest = entry.get("concurso")
        year = entry.get("year")

        if contest is not None:
            partition = f"c{contest}"
            filename = build_stamped_filename(
                base_id, partition, ext=ext, timestamp=last_modified
            )
        elif year is not None:
            partition = str(year)
            filename = build_stamped_filename(
                base_id, partition, ext=ext, timestamp=last_modified
            )
        else:
            filename = stamp_filename(base_id, ext, last_modified)

        return self.storage.path_for(f"{group}/{filename}")
