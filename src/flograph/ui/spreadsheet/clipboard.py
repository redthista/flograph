"""Clipboard payloads for spreadsheet cells.

Copy puts three formats on the clipboard at once: plain-text TSV of the
computed values (what Excel/Sheets/editors paste), a minimal HTML table
(what Excel prefers for rich paste), and an internal JSON format carrying
the raw cell sources so formulas survive an in-app copy/paste.
"""
from __future__ import annotations

import csv
import html
import io
import json
from typing import Optional

MIME_CELLS = "application/x-flograph-cells"


def block_to_tsv(rows: list[list[str]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter="\t", lineterminator="\n")
    writer.writerows(rows)
    text = out.getvalue()
    return text[:-1] if text.endswith("\n") else text


def block_to_html(rows: list[list[str]]) -> str:
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row)
        + "</tr>"
        for row in rows)
    return f"<table>{body}</table>"


def parse_paste_text(text: str) -> list[list[str]]:
    """TSV from the clipboard into a rectangular block of strings.

    Handles Excel's quirks: CRLF line endings, exactly one trailing
    newline after the block, and quoted cells holding tabs/newlines.
    """
    if not text:
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    rows = [row for row in csv.reader(io.StringIO(text), delimiter="\t")]
    if not rows:
        return []
    width = max(len(row) for row in rows)
    return [row + [""] * (width - len(row)) for row in rows]


def encode_cells(origin: tuple[int, int], rows: list[list[str]]) -> bytes:
    """Internal clipboard format: raw cell sources (formulas intact) plus
    the copy origin, so paste can shift relative references by the move."""
    return json.dumps({"origin": list(origin),
                       "cells": [list(row) for row in rows]}).encode("utf-8")


def decode_cells(payload: bytes) -> Optional[tuple[tuple[int, int],
                                                   list[list[str]]]]:
    try:
        data = json.loads(bytes(payload).decode("utf-8"))
        row, col = data["origin"]
        cells = data["cells"]
        assert isinstance(cells, list) and cells
        return (int(row), int(col)), [[str(v) for v in row_] for row_ in cells]
    except Exception:
        return None
