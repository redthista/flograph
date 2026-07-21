"""Extension -> reader-node mapping for OS file drag-drop onto the canvas."""
from __future__ import annotations

import os
from typing import Optional

# extension -> (node type_id, param name to prefill with the dropped path)
FILE_DROP_TARGETS: dict[str, tuple[str, str]] = {
    ".csv": ("flograph.io.read_csv", "path"),
    ".xlsx": ("flograph.io.read_excel", "path"),
    ".xls": ("flograph.io.read_excel", "path"),
    ".xlsm": ("flograph.io.read_excel", "path"),
    ".parquet": ("flograph.io.read_parquet", "path"),
}


def resolve_dropped_file(path: str) -> Optional[tuple[str, str]]:
    """Local file path -> (type_id, param_name), or None if unsupported."""
    ext = os.path.splitext(path)[1].lower()
    return FILE_DROP_TARGETS.get(ext)
