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
        """Compute the local path for a dataset entry.

        For A7 sources (dynamic export without reliable HTTP metadata), the server
        doesn't provide Last-Modified/ETag. Per ADR 2026-10-30 (F3: remote_only
        + CAS sha256), we use the download date as the timestamp so that each
        sync creates a new @YYYYMMDD version only when content actually changes
        (download_with_manifest compares sha256 before atomic commit).
        """
        group = entry.get("group", "concursos")
        ext = entry.get("ext", "xlsx")
        base_id = entry.get("base_id", entry.get("id", "loterias"))
        contest = entry.get("concurso")
        year = entry.get("year")

        # Fallback to today's date when server doesn't provide reliable metadata
        timestamp = last_modified or dt.date.today()

        if contest is not None:
            partition = f"c{contest}"
            filename = build_stamped_filename(
                base_id, partition, ext=ext, timestamp=timestamp
            )
        elif year is not None:
            partition = str(year)
            filename = build_stamped_filename(
                base_id, partition, ext=ext, timestamp=timestamp
            )
        else:
            filename = stamp_filename(base_id, ext, timestamp)

        return self.storage.path_for(f"{group}/{filename}")
