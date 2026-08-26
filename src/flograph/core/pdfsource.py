"""Resolving a PDF source: a file path, a `data:` URI, or bare base64.

Qt-free and stdlib-only, like the rest of `flograph.core` — imported both by
the PDF nodes' `run()` (which executes in an engine worker) and by the canvas
card (which paints on the GUI thread), so the two can never disagree about
what a given source string means. Exactly the job `core.images` does for
pictures, and the encoding half of it is borrowed from there rather than
written twice: a `data:` URI is a `data:` URI whatever it carries, and base64
does not know what it decodes to.

What is genuinely PDF-specific is the sniffing. A PDF announces itself with
`%PDF-` and, unlike an image, is allowed a little junk in front of it — the
spec says a reader should look for the header within the first 1024 bytes,
and files that have been through a mail gateway or a badly-behaved CGI script
often need that latitude. pdfium accepts them, so this does too.
"""
from __future__ import annotations

import os
from typing import Optional

from .images import decode_base64, looks_like_base64, parse_data_uri, to_data_uri

PDF_MIME = "application/pdf"

#: The header, and how far into the file it is allowed to appear.
_MAGIC = b"%PDF-"
_MAGIC_WINDOW = 1024

__all__ = ["PDF_MIME", "is_pdf_bytes", "resolve_source", "to_data_uri"]


def is_pdf_bytes(data: bytes) -> bool:
    """Whether `data` actually looks like a PDF."""
    return _MAGIC in data[:_MAGIC_WINDOW + len(_MAGIC)]


def resolve_source(source: str, need_bytes: bool = True
                   ) -> tuple[bytes, Optional[str]]:
    """Turn a PDF source string into (bytes, path-or-None).

    `path` is None whenever the document came from a string rather than a
    file, which is how callers tell "this lives on disk" from "these bytes
    are all there is" — the distinction the whole light/heavy payload choice
    rests on, since only a file can be re-read later for free.

    `need_bytes=False` is that choice made concrete: a source that is a file
    on disk is verified by reading its header and nothing more, and comes
    back with empty bytes. It is what keeps "metadata only" honest — a
    400MB scan should not pass through memory just to have its page count
    counted, and pdfium can read the file itself from the path. A source
    that is *not* a file ignores the flag, because there decoding is the
    only way to have a document at all.

    Raises ValueError/FileNotFoundError with a message meant for the user,
    since every caller surfaces it directly.
    """
    source = str(source or "").strip()
    if not source:
        raise ValueError(
            "no PDF given — set 'PDF file', drag a PDF onto the canvas, or "
            "wire in a path, a data: URI or a base64 string")

    if source[:5].lower() == "data:":
        parsed = parse_data_uri(source)
        if parsed is None:
            raise ValueError("that data: URI could not be decoded")
        data, _mime = parsed
        if not is_pdf_bytes(data):
            raise ValueError("that data: URI did not decode to a PDF")
        return data, None

    expanded = os.path.expanduser(source)
    try:
        on_disk = os.path.isfile(expanded)
    except (OSError, ValueError):
        # A multi-megabyte base64 blob is not a path any OS will look at.
        on_disk = False
    if on_disk:
        with open(expanded, "rb") as handle:
            data = (handle.read() if need_bytes
                    else handle.read(_MAGIC_WINDOW + len(_MAGIC)))
        if not data:
            raise ValueError(f"PDF file is empty: {expanded}")
        if not is_pdf_bytes(data):
            raise ValueError(
                f"that file does not start with a PDF header: {expanded}")
        return (data if need_bytes else b""), expanded

    if looks_like_base64(source):
        data = decode_base64(source)
        if data:
            if is_pdf_bytes(data):
                return data, None
            raise ValueError(
                "that base64 string decoded, but not into a PDF")

    # Looks like a path, so complain like one — that is the far commoner case.
    if len(source) < 260 and not looks_like_base64(source):
        raise FileNotFoundError(f"PDF file not found: {expanded}")
    raise ValueError(
        "could not read that PDF: it is not a file that exists, a data: URI, "
        "or a base64-encoded document")
