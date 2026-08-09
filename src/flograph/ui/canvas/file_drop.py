"""Extension -> reader-node mapping for OS file drag-drop onto the canvas."""
from __future__ import annotations

import os
from typing import Optional

_IMAGE_NODE = "flograph.viz.image"

# Picture formats the bundled Qt image plugins read. Deliberately a fixed
# list rather than QImageReader.supportedImageFormats(): this module is
# Qt-free (it is imported by the drag handler *and* by tests), and a drop
# target that silently varies with which plugins a given build shipped is
# worse than one that is always the same. Anything missing here can still be
# opened with the Image node's file picker.
IMAGE_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".jfif", ".gif", ".webp", ".bmp", ".svg",
    ".svgz", ".ico", ".tif", ".tiff", ".ppm", ".pgm", ".pbm", ".xpm",
    ".tga", ".icns",
)

# extension -> (node type_id, param name to prefill with the dropped path)
FILE_DROP_TARGETS: dict[str, tuple[str, str]] = {
    ".csv": ("flograph.io.read_csv", "path"),
    ".xlsx": ("flograph.io.read_excel", "path"),
    ".xls": ("flograph.io.read_excel", "path"),
    ".xlsm": ("flograph.io.read_excel", "path"),
    ".parquet": ("flograph.io.read_parquet", "path"),
    **{ext: (_IMAGE_NODE, "path") for ext in IMAGE_EXTENSIONS},
}


def resolve_dropped_file(path: str) -> Optional[tuple[str, str]]:
    """Local file path -> (type_id, param_name), or None if unsupported."""
    ext = os.path.splitext(path)[1].lower()
    return FILE_DROP_TARGETS.get(ext)
