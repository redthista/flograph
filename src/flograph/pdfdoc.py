"""Reading a PDF: one wrapper over Qt's bundled pdfium, shared by the nodes
and the canvas card.

Deliberately *not* in `flograph.core` — it imports Qt, and core is Qt-free by
a poison test. Equally deliberately not in `flograph.ui`: a node's `run()`
needs this and must never drag QtWidgets into an engine worker. So it sits
alongside `ai.py` and `packages.py` as a plain module with one job, importing
`QtPdf` and `QtCore` and nothing else.

Three properties of QtPdf make this possible at all, and all three were
measured rather than assumed:

1. **No QApplication is needed.** Loading, text extraction and rendering all
   work in a bare interpreter with no Qt application object, so a headless
   CLI run behaves exactly like the app.
2. **It works off the GUI thread.** `run()` executes in an engine worker, and
   a QPdfDocument built there is a QObject with that thread's affinity and no
   event loop — which is fine, because every call used here is synchronous.
3. **It is fast.** Load and per-page text are single-digit milliseconds on
   ordinary documents; a page rendered at card size costs a few more.

What it does not do, so nobody goes looking: no table extraction, no form
fields, no annotations, and no writing — pdfium here is a reader. Scanned
documents have no text layer at all and come back empty, which `has_text`
exists to let a caller say out loud rather than emit blank rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtPdf import QPdfDocument

#: What a page is rendered at when nobody says otherwise. A PDF point is
#: 1/72", so 150 dpi is a little over 2x — sharp on a normal screen without
#: the cost of print resolution.
DEFAULT_DPI = 150.0
POINTS_PER_INCH = 72.0

#: Ceiling on one rendered page, in pixels (~16MB at RGBA). The same guard
#: the image card puts on a decode, for the same reason: an A0 poster page at
#: 300 dpi is a 400MB allocation nobody asked for.
MAX_RENDER_PIXELS = 4_000_000

#: QPdfDocument.Error -> a sentence the user can act on. Qt's own strings are
#: enum names.
_ERRORS = {
    QPdfDocument.Error.FileNotFound: "file not found",
    QPdfDocument.Error.InvalidFileFormat: "not a readable PDF",
    QPdfDocument.Error.IncorrectPassword:
        "this PDF is password protected — set the Password parameter "
        "(a ${variable} works here)",
    QPdfDocument.Error.UnsupportedSecurityScheme:
        "this PDF uses a security scheme Qt cannot open",
    QPdfDocument.Error.DataNotYetAvailable: "the document is incomplete",
    QPdfDocument.Error.Unknown: "could not be opened",
}

_META_FIELDS = {
    "title": QPdfDocument.MetaDataField.Title,
    "author": QPdfDocument.MetaDataField.Author,
    "subject": QPdfDocument.MetaDataField.Subject,
    "keywords": QPdfDocument.MetaDataField.Keywords,
    "creator": QPdfDocument.MetaDataField.Creator,
    "producer": QPdfDocument.MetaDataField.Producer,
}
_DATE_FIELDS = {
    "created": QPdfDocument.MetaDataField.CreationDate,
    "modified": QPdfDocument.MetaDataField.ModificationDate,
}


class PdfError(RuntimeError):
    """A PDF that could not be opened. The message is user-facing."""


@dataclass
class PdfDocument:
    """An open PDF. Use it as a context manager, or call `close()`.

    Prefers reading from a path when there is one: pdfium then reads the file
    as it needs it rather than being handed the whole thing up front, which
    is the difference between a 400-page report costing a few MB and costing
    all of it. Bytes are used only when the source never was a file — a
    base64 blob out of an API or a database column.
    """

    _doc: QPdfDocument
    path: Optional[str] = None
    _buffer: Any = None
    _bytes: Any = field(default=None, repr=False)

    # ------------------------------------------------------------- opening

    @classmethod
    def open(cls, data: Optional[bytes], path: Optional[str] = None,
             password: str = "") -> "PdfDocument":
        """Open a document from a path, from bytes, or from both.

        Raises PdfError with a message meant for the user.
        """
        doc = QPdfDocument()
        if password:
            # Set before loading: pdfium wants the password at open time, and
            # loading first only to retry is a wasted parse of the whole file.
            doc.setPassword(password)
        buffer = byte_array = None
        if path:
            error = doc.load(path)
        elif data:
            # Both the QByteArray and the QBuffer must outlive the document,
            # which reads from them for as long as it is open — hence the
            # fields below rather than locals.
            byte_array = QByteArray(data)
            buffer = QBuffer()
            buffer.setData(byte_array)
            buffer.open(QIODevice.ReadOnly)
            doc.load(buffer)  # the device overload reports through error()
            error = doc.error()
        else:
            raise PdfError("no PDF data given")
        if error != QPdfDocument.Error.None_:
            where = f": {path}" if path else ""
            raise PdfError(_ERRORS.get(error, "could not be opened") + where)
        return cls(doc, path, buffer, byte_array)

    def close(self) -> None:
        self._doc.close()
        if self._buffer is not None:
            self._buffer.close()
            self._buffer = None
        self._bytes = None

    def __enter__(self) -> "PdfDocument":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # -------------------------------------------------------------- shape

    @property
    def page_count(self) -> int:
        return int(self._doc.pageCount())

    def page_size(self, page: int) -> tuple[float, float]:
        """(width, height) of a page in PDF points."""
        size = self._doc.pagePointSize(page)
        return float(size.width()), float(size.height())

    def page_label(self, page: int) -> str:
        """The page's printed label — "iv", "A-3" — which is not always its
        index plus one, and is what a reader would call it."""
        return str(self._doc.pageLabel(page) or "")

    def metadata(self) -> dict:
        """Document metadata as plain Python: strings and ISO dates.

        Dates arrive as QDateTime and leave as ISO strings, because the value
        travels into a DataFrame cell and out to a saved cache blob, and
        neither wants a Qt object in it.
        """
        meta: dict = {name: str(self._doc.metaData(f) or "")
                      for name, f in _META_FIELDS.items()}
        for name, field_id in _DATE_FIELDS.items():
            value = self._doc.metaData(field_id)
            stamp = getattr(value, "toString", None)
            meta[name] = (value.toString("yyyy-MM-ddTHH:mm:ss")
                          if stamp and value.isValid() else "")
        return meta

    # --------------------------------------------------------------- text

    def page_text(self, page: int) -> str:
        """The text layer of one page, or "" when it has none.

        Line endings are normalised on the way out. pdfium hands back CRLF
        and a DataFrame full of stray \\r is a nuisance in every downstream
        node that touches the column — this is not an option because there is
        no version of it anyone wants.
        """
        text = str(self._doc.getAllText(page).text() or "")
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def has_text(self, sample_pages: int = 4) -> bool:
        """Whether the document appears to have a text layer at all.

        Samples rather than reads everything: this exists so a node can warn
        "no text layer — this looks like a scan" without paying for a full
        extraction to find out.
        """
        for page in range(min(sample_pages, self.page_count)):
            if self.page_text(page).strip():
                return True
        return False

    # -------------------------------------------------------------- render

    def render(self, page: int, size: QSize):
        """One page as a QImage at exactly `size`, budget-clamped."""
        return self._doc.render(page, budgeted(size))

    def render_at_dpi(self, page: int, dpi: float = DEFAULT_DPI):
        """One page as a QImage at a resolution rather than a size."""
        return self.render(page, size_at_dpi(self.page_size(page), dpi))


# ------------------------------------------------------------ the payload

#: The two answers to "how much of this document should travel down the
#: wire". Light is the default everywhere: a document dict that names a file
#: costs a few hundred bytes in the cache and the next node re-opens it from
#: disk for free. Heavy carries the whole file, which is what you need when
#: the source never was a file (base64 out of an API or a blob column), when
#: the file will have moved or changed by the time the flow runs again, or
#: when a downstream node wants a `data_uri` to embed. The user picks; the
#: node does not guess.
PAYLOAD_LIGHT = "Metadata only"
PAYLOAD_HEAVY = "Metadata + bytes"
PAYLOAD_CHOICES = [PAYLOAD_LIGHT, PAYLOAD_HEAVY]


def document_payload(doc: "PdfDocument", source: str = "",
                     data: Optional[bytes] = None,
                     carry_bytes: bool = False) -> dict:
    """The dict every PDF node emits on its `document` port.

    One builder for all three nodes so a document means the same thing
    wherever it came from, and so the canvas card can read a wired one.
    `source` is echoed back untouched — it is how a source that arrived on a
    *wire* reaches the card, which otherwise only ever sees its own param.
    """
    from flograph.core.pdfsource import PDF_MIME, to_data_uri

    payload: dict = {
        "path": doc.path,
        "pages": doc.page_count,
        "mime": PDF_MIME,
        "source": source,
        "bytes": None,
        "data_uri": None,
        **doc.metadata(),
    }
    if carry_bytes and data:
        payload["bytes"] = data
        payload["data_uri"] = to_data_uri(data, PDF_MIME)
    elif carry_bytes and doc.path:
        with open(doc.path, "rb") as handle:
            blob = handle.read()
        payload["bytes"] = blob
        payload["data_uri"] = to_data_uri(blob, PDF_MIME)
    return payload


def size_at_dpi(page_size_pt: tuple[float, float],
                dpi: float = DEFAULT_DPI) -> QSize:
    """A page's point size as a pixel size at `dpi`."""
    scale = max(1.0, float(dpi)) / POINTS_PER_INCH
    return QSize(max(1, round(page_size_pt[0] * scale)),
                 max(1, round(page_size_pt[1] * scale)))


def budgeted(size: QSize) -> QSize:
    """`size` shrunk, in proportion, to fit inside MAX_RENDER_PIXELS."""
    pixels = size.width() * size.height()
    if pixels <= MAX_RENDER_PIXELS or pixels <= 0:
        return size
    scale = (MAX_RENDER_PIXELS / pixels) ** 0.5
    return QSize(max(1, int(size.width() * scale)),
                 max(1, int(size.height() * scale)))


def parse_page_range(spec: str, page_count: int) -> list[int]:
    """"1-3, 7, 10-" -> [0, 1, 2, 6, 9, ...] — 0-based, sorted, deduplicated.

    One-based and inclusive because that is what the page numbers in a PDF
    reader say, and a user typing a range is reading it off one of those.
    An empty spec means every page. Raises ValueError on nonsense.
    """
    spec = str(spec or "").strip()
    if not spec:
        return list(range(page_count))
    pages: set[int] = set()
    for chunk in spec.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Any dash makes it a range, including a leading one: "-2" means
        # "up to page 2". There are no negative page numbers for it to be
        # confused with.
        if "-" in chunk:
            head, _, tail = chunk.partition("-")
            start = _one_based(head, 1)
            end = _one_based(tail, page_count)
        else:
            start = end = _one_based(chunk, None)
        if start > end:
            start, end = end, start
        pages.update(range(max(1, start), min(page_count, end) + 1))
    return [page - 1 for page in sorted(pages)]


def _one_based(text: str, default: Optional[int]) -> int:
    text = text.strip()
    if not text:
        if default is None:
            raise ValueError("empty page number in the page range")
        return default
    try:
        return int(text)
    except ValueError:
        raise ValueError(
            f"{text!r} is not a page number — use forms like 1-3, 7, 10-"
        ) from None
