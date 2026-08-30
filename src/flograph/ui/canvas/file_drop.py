"""What an OS drag-drop onto the canvas becomes: a file maps by extension to
a reader/viewer node, a folder of `.md` files to a Markdown Wiki node."""
from __future__ import annotations

import glob
import os
from typing import Optional

_IMAGE_NODE = "flograph.viz.image"
_PDF_NODE = "flograph.viz.pdf_viewer"

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
    # A dropped PDF opens in the viewer rather than the reader: a
    # document you drag onto a canvas is one you want to look at, and
    # Read PDF is one wire away once you do.
    ".pdf": (_PDF_NODE, "path"),
    **{ext: (_IMAGE_NODE, "path") for ext in IMAGE_EXTENSIONS},
}

_WIKI_NODE = "flograph.viz.markdown_wiki"


def resolve_dropped_file(path: str) -> Optional[tuple[str, str]]:
    """Local file path -> (type_id, param_name), or None if unsupported."""
    ext = os.path.splitext(path)[1].lower()
    return FILE_DROP_TARGETS.get(ext)


def resolve_dropped_folder(path: str) -> Optional[tuple[str, str]]:
    """A folder that holds at least one top-level `.md` file -> the Markdown
    Wiki node, prefilling its `folder` param. Any other folder is left alone,
    so dropping an arbitrary directory is not silently turned into a wiki."""
    if not os.path.isdir(path):
        return None
    if not glob.glob(os.path.join(glob.escape(path), "*.md")):
        return None
    return (_WIKI_NODE, "folder")


def resolve_dropped_path(path: str) -> Optional[tuple[str, str]]:
    """A dropped path -> (type_id, param_name), file or folder."""
    if os.path.isdir(path):
        return resolve_dropped_folder(path)
    return resolve_dropped_file(path)
