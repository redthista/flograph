"""The PDF family: the source resolver, the pdfium wrapper, both readers, the
viewer node and its canvas card.

The documents under test are built here rather than checked in as binary
fixtures. A PDF is a text format, so forty lines of `build_pdf` gives every
test exactly the document it needs — two pages, no text layer, a bad header —
which a folder of committed sample files could not do without becoming a
folder of committed sample files nobody dares change.

Note that *writing* a PDF with Qt (QPdfWriter) needs a QGuiApplication for its
font database, while *reading* one needs no application object at all. That
asymmetry is why the generator below is hand-rolled: it has to work in a
headless run, which only ever gets a QCoreApplication.
"""
import base64
import json

import pytest

from flograph.core import compile_run
from flograph.core.pdfsource import PDF_MIME, is_pdf_bytes, resolve_source, to_data_uri
from flograph import pdfdoc
from tests.conftest import FakeContext


# --------------------------------------------------------------- fixtures

def build_pdf(pages, title=""):
    """A minimal single-font PDF as bytes. `pages` is a list of line-lists."""
    def esc(text):
        return (str(text).replace("\\", r"\\")
                .replace("(", r"\(").replace(")", r"\)"))

    objects, page_ids = [], []
    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(None)
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for lines in pages:
        content = ["BT", "/F1 16 Tf", "24 TL", "72 760 Td"]
        content += [f"({esc(line)}) Tj T*" for line in lines]
        content.append("ET")
        stream = "\n".join(content)
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            "/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {len(objects) + 2} 0 R >>")
        page_ids.append(len(objects))
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    info_ref = 0
    if title:
        objects.append(f"<< /Title ({esc(title)}) >>")
        info_ref = len(objects)
    objects[1] = ("<< /Type /Pages /Kids ["
                  + " ".join(f"{i} 0 R" for i in page_ids)
                  + f"] /Count {len(pages)} >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")
    info = f" /Info {info_ref} 0 R" if info_ref else ""
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R{info} >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode("latin-1")
    return bytes(out)


TWO_PAGES = [["Invoice A-100", "Acme Ltd"], ["terms and conditions"]]


@pytest.fixture
def invoice(tmp_path):
    path = tmp_path / "invoice.pdf"
    path.write_bytes(build_pdf(TWO_PAGES, "Invoice A"))
    return path


@pytest.fixture
def folder(tmp_path):
    """A folder holding a two-pager, a one-pager, a scan with no text layer,
    and a file that is not a PDF at all."""
    (tmp_path / "a_invoice.pdf").write_bytes(build_pdf(TWO_PAGES, "Invoice A"))
    (tmp_path / "b_note.pdf").write_bytes(build_pdf([["short note"]], "Note B"))
    (tmp_path / "c_scan.pdf").write_bytes(build_pdf([[]], "Scan C"))
    (tmp_path / "d_broken.pdf").write_bytes(b"%PDF-1.4\nnot really\n")
    return tmp_path


@pytest.fixture
def nested_folder(tmp_path):
    """One PDF at the top and one down each of two branches."""
    (tmp_path / "top.pdf").write_bytes(build_pdf([["top"]], "Top"))
    for rel, title in [("2026/signed/deal.pdf", "Deal"),
                       ("archive/2019/old.pdf", "Old")]:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(build_pdf([[title.lower()]], title))
    return tmp_path


def run_node(registry, type_id, params=None, **inputs):
    spec = registry.get(type_id)
    defaults = spec.default_params()
    defaults.update(params or {})
    run = compile_run(spec.source, f"test-{type_id}")
    return run(FakeContext(params=defaults), **inputs)


# ------------------------------------------------------- the source resolver

class TestPdfSource:
    def test_a_path_resolves_to_bytes_and_the_path(self, invoice):
        data, path = resolve_source(str(invoice))
        assert is_pdf_bytes(data)
        assert path == str(invoice)

    def test_metadata_only_reads_the_header_not_the_file(self, invoice):
        """The whole point of the light payload: a 400MB scan must not pass
        through memory to have its page count counted."""
        data, path = resolve_source(str(invoice), need_bytes=False)
        assert data == b""
        assert path == str(invoice)

    def test_a_data_uri_resolves_with_no_path(self, invoice):
        uri = to_data_uri(invoice.read_bytes(), PDF_MIME)
        data, path = resolve_source(uri)
        assert is_pdf_bytes(data)
        assert path is None

    def test_bare_base64_resolves(self, invoice):
        blob = base64.b64encode(invoice.read_bytes()).decode("ascii")
        data, path = resolve_source(blob)
        assert is_pdf_bytes(data) and path is None

    def test_need_bytes_is_ignored_for_a_string_source(self, invoice):
        """There is no file to re-read later, so the bytes are all there is."""
        uri = to_data_uri(invoice.read_bytes(), PDF_MIME)
        data, _path = resolve_source(uri, need_bytes=False)
        assert is_pdf_bytes(data)

    def test_a_header_may_sit_a_little_way_into_the_file(self, tmp_path):
        path = tmp_path / "preamble.pdf"
        path.write_bytes(b"\n" * 40 + build_pdf([["hi"]]))
        data, _ = resolve_source(str(path))
        assert is_pdf_bytes(data)

    def test_an_empty_source_says_what_to_do(self):
        with pytest.raises(ValueError, match="no PDF given"):
            resolve_source("")

    def test_a_missing_file_complains_like_a_path(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            resolve_source("/no/such/file.pdf")

    def test_a_file_that_is_not_a_pdf_is_refused(self, tmp_path):
        path = tmp_path / "fake.pdf"
        path.write_bytes(b"this is a text file")
        with pytest.raises(ValueError, match="PDF header"):
            resolve_source(str(path))

    def test_an_empty_file_is_refused(self, tmp_path):
        path = tmp_path / "empty.pdf"
        path.write_bytes(b"")
        with pytest.raises(ValueError, match="empty"):
            resolve_source(str(path))

    def test_base64_of_something_else_is_refused(self):
        blob = base64.b64encode(b"x" * 200).decode("ascii")
        with pytest.raises(ValueError, match="not into a PDF"):
            resolve_source(blob)


# ------------------------------------------------------------- the wrapper

class TestPdfDocument:
    def test_it_opens_from_a_path(self, invoice):
        with pdfdoc.PdfDocument.open(None, str(invoice)) as doc:
            assert doc.page_count == 2
            assert doc.metadata()["title"] == "Invoice A"

    def test_it_opens_from_bytes_with_no_file(self, invoice):
        with pdfdoc.PdfDocument.open(invoice.read_bytes(), None) as doc:
            assert doc.page_count == 2
            assert doc.path is None

    def test_page_text_normalises_line_endings(self, invoice):
        with pdfdoc.PdfDocument.open(None, str(invoice)) as doc:
            text = doc.page_text(0)
        assert "\r" not in text
        assert text.splitlines() == ["Invoice A-100", "Acme Ltd"]

    def test_page_size_is_in_points(self, invoice):
        with pdfdoc.PdfDocument.open(None, str(invoice)) as doc:
            assert doc.page_size(0) == (595.0, 842.0)

    def test_has_text_is_false_for_a_scan(self, tmp_path):
        path = tmp_path / "scan.pdf"
        path.write_bytes(build_pdf([[], []]))
        with pdfdoc.PdfDocument.open(None, str(path)) as doc:
            assert doc.has_text() is False

    def test_render_produces_an_image_of_the_asked_for_size(self, invoice):
        from PySide6.QtCore import QSize
        with pdfdoc.PdfDocument.open(None, str(invoice)) as doc:
            image = doc.render(0, QSize(120, 170))
        assert not image.isNull()
        assert image.size() == QSize(120, 170)

    def test_a_broken_file_raises_a_readable_error(self, tmp_path):
        path = tmp_path / "broken.pdf"
        path.write_bytes(b"%PDF-1.4\nnope\n")
        with pytest.raises(pdfdoc.PdfError, match="not a readable PDF"):
            pdfdoc.PdfDocument.open(None, str(path))

    def test_a_render_is_clamped_to_the_pixel_budget(self):
        from PySide6.QtCore import QSize
        huge = QSize(8000, 8000)
        clamped = pdfdoc.budgeted(huge)
        assert clamped.width() * clamped.height() <= pdfdoc.MAX_RENDER_PIXELS
        # and in proportion
        assert clamped.width() == clamped.height()

    def test_size_at_dpi(self):
        assert pdfdoc.size_at_dpi((72.0, 144.0), 72.0).width() == 72
        assert pdfdoc.size_at_dpi((72.0, 144.0), 144.0).height() == 288


class TestPageRange:
    @pytest.mark.parametrize("spec,expected", [
        ("", [0, 1, 2, 3, 4]),
        ("1", [0]),
        ("1-3", [0, 1, 2]),
        ("1-3, 5", [0, 1, 2, 4]),
        ("4-", [3, 4]),
        ("-2", [0, 1]),
        ("3-1", [0, 1, 2]),        # backwards ranges are read charitably
        ("2, 2, 2", [1]),          # deduplicated
        ("4-99", [3, 4]),          # clamped to the document
    ])
    def test_ranges(self, spec, expected):
        assert pdfdoc.parse_page_range(spec, 5) == expected

    def test_nonsense_is_refused_by_name(self):
        with pytest.raises(ValueError, match="not a page number"):
            pdfdoc.parse_page_range("one-two", 5)


# ------------------------------------------------------------- the payload

class TestPayload:
    def test_light_carries_the_path_and_no_bytes(self, invoice):
        with pdfdoc.PdfDocument.open(None, str(invoice)) as doc:
            payload = pdfdoc.document_payload(doc, str(invoice), None, False)
        assert payload["path"] == str(invoice)
        assert payload["bytes"] is None and payload["data_uri"] is None
        assert payload["pages"] == 2 and payload["title"] == "Invoice A"

    def test_heavy_carries_the_file_and_a_data_uri(self, invoice):
        with pdfdoc.PdfDocument.open(None, str(invoice)) as doc:
            payload = pdfdoc.document_payload(doc, str(invoice), None, True)
        assert payload["bytes"] == invoice.read_bytes()
        assert payload["data_uri"].startswith(f"data:{PDF_MIME};base64,")

    def test_the_source_is_echoed_back_for_the_card(self, invoice):
        """A source that arrived on a wire reaches the canvas only this way."""
        with pdfdoc.PdfDocument.open(None, str(invoice)) as doc:
            payload = pdfdoc.document_payload(doc, "some://source", None, False)
        assert payload["source"] == "some://source"


# -------------------------------------------------------------- Read PDF

class TestReadPdf:
    def test_it_gives_one_row_per_page(self, registry, invoice):
        out = run_node(registry, "flograph.io.read_pdf", {"path": str(invoice)})
        pages = out["pages"]
        assert list(pages["page"]) == [1, 2]
        assert list(pages["text"]) == ["Invoice A-100\nAcme Ltd",
                                       "terms and conditions"]
        assert list(pages["words"]) == [4, 3]
        assert list(pages["width_pt"]) == [595.0, 595.0]

    def test_the_document_port_carries_the_metadata(self, registry, invoice):
        out = run_node(registry, "flograph.io.read_pdf", {"path": str(invoice)})
        assert out["document"]["title"] == "Invoice A"
        assert out["document"]["pages"] == 2
        assert out["document"]["bytes"] is None  # light by default

    def test_the_heavy_payload_carries_the_file(self, registry, invoice):
        out = run_node(registry, "flograph.io.read_pdf",
                       {"path": str(invoice), "payload": "Metadata + bytes"})
        assert out["document"]["bytes"] == invoice.read_bytes()

    def test_a_page_range_limits_the_read(self, registry, invoice):
        out = run_node(registry, "flograph.io.read_pdf",
                       {"path": str(invoice), "pages": "2"})
        assert list(out["pages"]["page"]) == [2]

    def test_extraction_off_leaves_the_page_inventory(self, registry, invoice):
        out = run_node(registry, "flograph.io.read_pdf",
                       {"path": str(invoice), "extract_text": False})
        assert list(out["pages"].columns) == ["page", "label", "width_pt",
                                              "height_pt"]
        assert len(out["pages"]) == 2

    def test_skip_empty_drops_pages_with_no_text(self, registry, tmp_path):
        path = tmp_path / "mixed.pdf"
        path.write_bytes(build_pdf([["real text here"], []]))
        out = run_node(registry, "flograph.io.read_pdf",
                       {"path": str(path), "skip_empty": True})
        assert list(out["pages"]["page"]) == [1]

    def test_a_scan_is_called_out_in_the_log(self, registry, tmp_path):
        path = tmp_path / "scan.pdf"
        path.write_bytes(build_pdf([[], []]))
        spec = registry.get("flograph.io.read_pdf")
        params = spec.default_params()
        params["path"] = str(path)
        ctx = FakeContext(params=params)
        compile_run(spec.source, "t")(ctx)
        assert any("scanned document" in line for line in ctx.logs)

    def test_a_wired_path_beats_the_parameter(self, registry, invoice, tmp_path):
        other = tmp_path / "other.pdf"
        other.write_bytes(build_pdf([["only one page"]], "Other"))
        out = run_node(registry, "flograph.io.read_pdf",
                       {"path": str(invoice)}, path_input=str(other))
        assert out["document"]["title"] == "Other"

    def test_no_source_at_all_says_what_to_do(self, registry):
        with pytest.raises(ValueError, match="no PDF selected"):
            run_node(registry, "flograph.io.read_pdf", {})

    def test_a_range_selecting_nothing_is_an_error(self, registry, invoice):
        with pytest.raises(ValueError, match="selects no pages"):
            run_node(registry, "flograph.io.read_pdf",
                     {"path": str(invoice), "pages": "9-12"})


# ------------------------------------------------------ Read PDF (Folder)

class TestReadPdfFolder:
    def test_it_stacks_every_document_with_a_file_column(self, registry, folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(folder)})
        pages = out["pages"]
        assert list(pages["file"]) == ["a_invoice.pdf", "a_invoice.pdf",
                                       "b_note.pdf", "c_scan.pdf"]
        assert list(pages["page"]) == [1, 2, 1, 1]

    def test_a_broken_file_gets_a_row_not_a_dead_run(self, registry, folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(folder)})
        docs = out["documents"].set_index("file")
        assert "not a readable PDF" in docs.loc["d_broken.pdf", "error"]
        assert docs.loc["d_broken.pdf", "pages"] == 0
        # and the good documents still came through
        assert docs.loc["a_invoice.pdf", "pages"] == 2
        assert docs.loc["a_invoice.pdf", "error"] == ""

    def test_a_failure_row_carries_every_column(self, registry, folder):
        """One bad file must not turn the metadata columns into NaN."""
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(folder)})
        assert not out["documents"].isna().any().any()

    def test_stop_on_error_raises_instead(self, registry, folder):
        with pytest.raises(Exception, match="not a readable PDF"):
            run_node(registry, "flograph.io.read_pdf_folder",
                     {"path": str(folder), "stop_on_error": True})

    def test_has_text_flags_the_scan(self, registry, folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(folder)})
        docs = out["documents"].set_index("file")
        assert bool(docs.loc["a_invoice.pdf", "has_text"]) is True
        assert bool(docs.loc["c_scan.pdf", "has_text"]) is False

    def test_include_patterns_filter_the_folder(self, registry, folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(folder), "include_pattern": "a_*.pdf"})
        assert set(out["documents"]["file"]) == {"a_invoice.pdf"}

    def test_exclude_patterns_filter_the_folder(self, registry, folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(folder), "exclude_pattern": "d_*"})
        assert "d_broken.pdf" not in set(out["documents"]["file"])

    def test_subfolders_are_left_alone_unless_asked_for(self, registry,
                                                       nested_folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(nested_folder)})
        assert list(out["pages"]["file"]) == ["top.pdf"]
        assert "folder" not in out["pages"].columns

    def test_a_recursive_read_says_which_branch_each_page_came_from(
            self, registry, nested_folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(nested_folder), "recursive": True})
        pages = out["pages"]
        assert list(pages.columns[:2]) == ["file", "folder"]
        assert dict(zip(pages["file"], pages["folder"])) == {
            "top.pdf": ".", "deal.pdf": "2026/signed", "old.pdf": "archive/2019"}
        assert set(out["documents"]["folder"]) == {".", "2026/signed",
                                                   "archive/2019"}

    def test_excluding_a_folder_takes_its_subtree(self, registry,
                                                  nested_folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(nested_folder), "recursive": True,
                        "exclude_dirs": "archive"})
        assert list(out["pages"]["file"]) == ["deal.pdf", "top.pdf"]

    def test_folder_patterns_are_inert_on_a_flat_read(self, registry,
                                                     nested_folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(nested_folder), "include_dirs": "2026*"})
        assert list(out["pages"]["file"]) == ["top.pdf"]

    def test_max_pages_caps_a_long_document(self, registry, folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(folder), "max_pages": 1})
        assert list(out["pages"]["page"]) == [1, 1, 1]

    def test_the_light_payload_leaves_no_byte_columns(self, registry, folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(folder)})
        assert "bytes" not in out["documents"].columns
        assert "data_uri" not in out["documents"].columns

    def test_the_heavy_payload_adds_them(self, registry, folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(folder), "payload": "Metadata + bytes"})
        docs = out["documents"].set_index("file")
        assert docs.loc["a_invoice.pdf", "bytes"] == \
            (folder / "a_invoice.pdf").read_bytes()
        assert docs.loc["a_invoice.pdf", "data_uri"].startswith("data:")
        # the failed one still has the columns, empty
        assert docs.loc["d_broken.pdf", "bytes"] is None

    def test_extraction_off_leaves_the_inventory(self, registry, folder):
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(folder), "extract_text": False})
        assert list(out["pages"].columns) == ["file", "page", "label",
                                              "width_pt", "height_pt"]

    def test_an_empty_folder_says_so(self, registry, tmp_path):
        with pytest.raises(ValueError, match="no .pdf files"):
            run_node(registry, "flograph.io.read_pdf_folder",
                     {"path": str(tmp_path)})

    def test_a_wired_folder_beats_the_parameter(self, registry, folder, tmp_path):
        empty = tmp_path / "elsewhere"
        empty.mkdir()
        out = run_node(registry, "flograph.io.read_pdf_folder",
                       {"path": str(empty)}, path_input=str(folder))
        assert len(out["documents"]) == 4


# ------------------------------------------------------------- the viewer

class TestPdfViewerNode:
    def test_it_emits_a_document_from_a_path(self, registry, invoice):
        out = run_node(registry, "flograph.viz.pdf_viewer",
                       {"path": str(invoice)})
        assert out["document"]["pages"] == 2
        assert out["document"]["title"] == "Invoice A"

    def test_it_accepts_a_document_dict_from_read_pdf(self, registry, invoice):
        """Wiring Read PDF straight into the viewer is the usual shape, so
        the dict must not need an Expression node to unpack it."""
        read = run_node(registry, "flograph.io.read_pdf",
                        {"path": str(invoice)})
        out = run_node(registry, "flograph.viz.pdf_viewer", {},
                       source=read["document"])
        assert out["document"]["pages"] == 2

    def test_a_wired_string_works_too(self, registry, invoice):
        out = run_node(registry, "flograph.viz.pdf_viewer", {},
                       source=str(invoice))
        assert out["document"]["pages"] == 2

    def test_the_heavy_payload_is_available_here_too(self, registry, invoice):
        out = run_node(registry, "flograph.viz.pdf_viewer",
                       {"path": str(invoice), "payload": "Metadata + bytes"})
        assert out["document"]["data_uri"].startswith("data:")

    def test_no_source_says_what_to_do(self, registry):
        with pytest.raises(ValueError, match="no PDF given"):
            run_node(registry, "flograph.viz.pdf_viewer", {})

    def test_it_declares_the_pdf_card(self, registry):
        from flograph.core.script import CARD_KINDS
        spec = registry.get("flograph.viz.pdf_viewer")
        assert spec.card == "pdf"
        assert "pdf" in CARD_KINDS


# ---------------------------------------------------------------- the card

class TestCardPdf:
    def _card(self, source, **kwargs):
        from flograph.ui.canvas.pdf_card import CardPdf
        card = CardPdf(lambda: None)
        card.set_source(str(source), **kwargs)
        return card

    def test_it_opens_a_document_and_counts_its_pages(self, qapp, invoice):
        card = self._card(invoice)
        assert card.has_content()
        assert card.page_count() == 2
        assert card.page_caption() == "1 / 2"

    def test_the_page_number_is_one_based(self, qapp, invoice):
        card = self._card(invoice, page=2)
        assert card.page_caption() == "2 / 2"

    def test_a_page_past_the_end_shows_the_last_one(self, qapp, invoice):
        """The number is a parameter someone is dragging — a document that
        got shorter should not turn the card into an error message."""
        card = self._card(invoice, page=99)
        assert card.page_caption() == "2 / 2"
        assert not card.error

    def test_shown_page_is_the_clamped_one(self, qapp, invoice):
        """What the pager steps from — the page on screen, not the number in
        the param, or a card left on page 99 would count up from there."""
        assert self._card(invoice, page=99).shown_page() == 2
        assert self._card(invoice, page=1).shown_page() == 1

    def test_the_natural_size_is_the_page_size(self, qapp, invoice):
        assert card_size(self._card(invoice)) == (595, 842)

    def test_an_empty_source_is_blank_not_an_error(self, qapp):
        card = self._card("")
        assert not card.has_content()
        assert card.error == ""

    def test_a_missing_file_becomes_a_message(self, qapp, tmp_path):
        card = self._card(tmp_path / "nope.pdf")
        assert not card.has_content()
        assert "not found" in card.error

    def test_it_renders_a_page_onto_white_paper(self, qapp, invoice):
        """pdfium draws the marks, not the paper — a page dropped straight
        onto a dark card would be black text on a dark body."""
        from PySide6.QtCore import QRectF, QSize
        from PySide6.QtGui import QImage, QPainter
        from flograph.ui.canvas.pdf_card import on_paper

        with pdfdoc.PdfDocument.open(None, str(invoice)) as doc:
            page = doc.render(0, QSize(60, 85))
        paper = on_paper(page)
        assert paper.format() == QImage.Format_RGB32
        # a corner of an invoice is blank paper, so it must be white
        assert paper.pixelColor(2, 2).name() == "#ffffff"

    def test_it_paints_without_error(self, qapp, invoice):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage, QPainter
        card = self._card(invoice)
        image = QImage(200, 260, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        card.paint(painter, QRectF(0, 0, 200, 260), 1.0)
        painter.end()
        assert not card.error
        # something was actually drawn
        assert any(image.pixelColor(x, y).alpha()
                   for x in range(0, 200, 20) for y in range(0, 260, 20))

    def test_a_document_dict_supplies_the_source(self, qapp, registry, invoice):
        from flograph.ui.canvas.pdf_card import pdf_source
        read = run_node(registry, "flograph.io.read_pdf",
                        {"path": str(invoice)})
        node = registry.instantiate("flograph.viz.pdf_viewer")
        assert pdf_source(node, read["document"]) == str(invoice)

    def test_the_node_param_is_the_fallback(self, qapp, registry, invoice):
        from flograph.ui.canvas.pdf_card import pdf_source
        node = registry.instantiate("flograph.viz.pdf_viewer")
        node.params["path"] = str(invoice)
        assert pdf_source(node, None) == str(invoice)


def card_size(card):
    size = card.natural_size()
    return size.width(), size.height()


# ------------------------------------------------------------- integration

class TestCanvasIntegration:
    def test_dropping_a_pdf_opens_the_viewer(self):
        from flograph.ui.canvas.file_drop import resolve_dropped_file
        assert resolve_dropped_file("/tmp/report.pdf") == (
            "flograph.viz.pdf_viewer", "path")
        assert resolve_dropped_file("/tmp/REPORT.PDF") == (
            "flograph.viz.pdf_viewer", "path")

    def test_the_node_item_builds_a_pdf_card(self, qapp, registry, invoice):
        from flograph.ui.canvas.node_item import NodeItem
        from flograph.ui.canvas.pdf_card import CardPdf
        node = registry.instantiate("flograph.viz.pdf_viewer")
        node.params["path"] = str(invoice)
        item = NodeItem(node)
        assert item.pdf_card
        # it rides the image card's geometry, chrome and resizing
        assert item.image_card
        assert isinstance(item._card_image(), CardPdf)
        assert item._card_image().page_count() == 2

    def test_an_image_node_still_builds_an_image_card(self, qapp, registry):
        from flograph.ui.canvas.node_item import NodeItem
        from flograph.ui.canvas.image_card import CardImage
        node = registry.instantiate("flograph.viz.image")
        item = NodeItem(node)
        assert not item.pdf_card and item.image_card
        assert isinstance(item._card_image(), CardImage)

    def test_a_pdf_node_can_be_a_dashboard_tile(self, registry):
        from flograph.ui.dashboard.tile_item import (default_tile_port,
                                                     default_tile_size,
                                                     is_tile_able)
        node = registry.instantiate("flograph.viz.pdf_viewer")
        assert is_tile_able(node)
        assert default_tile_port(node) == "document"
        width, height = default_tile_size(node)
        assert (width, height) == (320.0, 420.0 + 24.0)


# ---------------------------------------------------------------- the pager

def paint_item(item):
    """Draw a node item once, offscreen. The pager's hit rectangles are
    established by the paint that draws them, so a test that clicks a
    chevron has to draw the card first — which is exactly the rule the
    feature relies on: no chevron on screen, no chevron to click."""
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionGraphicsItem
    image = QImage(1, 1, QImage.Format_ARGB32)
    painter = QPainter(image)
    item.paint(painter, QStyleOptionGraphicsItem(), None)
    painter.end()


def click(item, pos):
    """A left-click on a node item at `pos`, in item coordinates."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent
    event = QGraphicsSceneMouseEvent(QEvent.GraphicsSceneMousePress)
    event.setPos(pos)
    event.setButton(Qt.LeftButton)
    event.setButtons(Qt.LeftButton)
    item.mousePressEvent(event)


class TestCardPager:
    """The chevrons either side of "2 / 3" at the bottom of a PDF card.

    Paging is a cosmetic param edit, so a click here turns the page and runs
    nothing — which is the whole point of the control: a document you have
    to go and press Run to leaf through is not a document.
    """

    @pytest.fixture
    def env(self, qtbot, registry, tmp_path):
        from PySide6.QtGui import QUndoStack
        from flograph.core import Graph
        from flograph.ui.canvas import NodeGraphScene
        path = tmp_path / "three.pdf"
        path.write_bytes(build_pdf([["one"], ["two"], ["three"]], "Three"))
        graph = Graph()
        stack = QUndoStack()
        scene = NodeGraphScene(graph, stack, registry=registry)
        node = graph.add_node(registry.instantiate("flograph.viz.pdf_viewer"))
        node.params["path"] = str(path)
        node.dirty = False
        item = scene.node_items[node.id]
        paint_item(item)
        yield graph, node, item, stack
        stack.clear()

    def test_a_multi_page_document_gets_chevrons(self, env):
        _graph, _node, item, _stack = env
        assert item._pager is not None
        back, forward = item._pager
        assert back.right() < forward.left()   # one at each end of the pill

    def test_a_single_page_document_gets_none(self, qtbot, registry, invoice,
                                              tmp_path):
        from PySide6.QtGui import QUndoStack
        from flograph.core import Graph
        from flograph.ui.canvas import NodeGraphScene
        path = tmp_path / "one.pdf"
        path.write_bytes(build_pdf([["only page"]], "One"))
        graph = Graph()
        stack = QUndoStack()
        scene = NodeGraphScene(graph, stack, registry=registry)
        node = graph.add_node(registry.instantiate("flograph.viz.pdf_viewer"))
        node.params["path"] = str(path)
        item = scene.node_items[node.id]
        paint_item(item)
        # the caption still says which page it is; there is just nowhere to go
        assert item._card_image().page_caption() == "1 / 1"
        assert item._pager is None
        stack.clear()

    def test_clicking_forward_turns_the_page(self, env):
        graph, node, item, _stack = env
        click(item, item._pager[1].center())
        assert node.params["page"] == 2
        assert item._card_image().page_caption() == "2 / 3"

    def test_clicking_back_turns_it_the_other_way(self, env):
        graph, node, item, _stack = env
        graph.set_param(node.id, "page", 3)
        click(item, item._pager[0].center())
        assert node.params["page"] == 2

    def test_it_stops_at_the_ends(self, env):
        graph, node, item, _stack = env
        click(item, item._pager[0].center())
        assert node.params["page"] == 1
        graph.set_param(node.id, "page", 3)
        click(item, item._pager[1].center())
        assert node.params["page"] == 3

    def test_it_steps_from_the_page_on_screen(self, env):
        """A page number left past the end of a shorter document shows the
        last page — so back from there is the page before that one, not 98."""
        graph, node, item, _stack = env
        graph.set_param(node.id, "page", 99)
        click(item, item._pager[0].center())
        assert node.params["page"] == 2

    def test_turning_the_page_runs_nothing(self, env):
        graph, node, item, _stack = env
        click(item, item._pager[1].center())
        assert not node.dirty

    def test_it_is_one_undo_step_per_flick(self, env):
        graph, node, item, stack = env
        click(item, item._pager[1].center())
        click(item, item._pager[1].center())
        assert node.params["page"] == 3
        stack.undo()
        assert node.params["page"] == 1   # back where the flick started

    def test_the_rest_of_the_card_does_not_page(self, env):
        from PySide6.QtCore import QPointF
        _graph, node, item, _stack = env
        click(item, QPointF(item.width / 2, item.body_height / 2))
        assert node.params["page"] == 1

    def test_a_flattened_card_has_nothing_to_click(self, env):
        """Zoomed far out the card is a coloured slab — the chevrons are not
        drawn, so the rectangles they left behind must not still fire."""
        _graph, node, item, _stack = env
        pos = item._pager[1].center()
        item._flat = True
        click(item, pos)
        assert node.params["page"] == 1

    def test_the_hovered_chevron_lights_up(self, env):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtWidgets import QGraphicsSceneHoverEvent
        _graph, _node, item, _stack = env
        event = QGraphicsSceneHoverEvent(QEvent.GraphicsSceneHoverMove)
        event.setPos(item._pager[1].center())
        item.hoverMoveEvent(event)
        assert item._pager_hover == 1
        event.setPos(QPointF(item.width / 2, item.body_height / 2))
        item.hoverMoveEvent(event)
        assert item._pager_hover == 0


class TestPagingAWiredDocument:
    """A viewer fed by a wire — Read PDF, or a folder read and filtered down
    to one row — draws the document its last run resolved. Turning the page
    must not throw that away: it did once, and the card emptied until the
    flow was dirtied and run again, which made a cosmetic param look like a
    data one."""

    @pytest.fixture
    def env(self, qtbot, registry, tmp_path):
        from PySide6.QtGui import QUndoStack
        from flograph.core import Graph
        from flograph.ui.canvas import NodeGraphScene
        path = tmp_path / "wired.pdf"
        path.write_bytes(build_pdf([["one"], ["two"], ["three"]], "Wired"))
        graph = Graph()
        stack = QUndoStack()
        scene = NodeGraphScene(graph, stack, registry=registry)
        node = graph.add_node(registry.instantiate("flograph.viz.pdf_viewer"))
        item = scene.node_items[node.id]
        # no file picked by hand: the source arrived on the wire, which is
        # what the engine reports when the node has run
        item.set_image_result(str(path))
        yield graph, node, item, path, stack
        stack.clear()

    def test_the_run_source_draws_the_card(self, env):
        _graph, _node, item, _path, _stack = env
        assert item._card_image().page_caption() == "1 / 3"

    def test_turning_the_page_keeps_it(self, env):
        graph, node, item, _path, _stack = env
        graph.set_param(node.id, "page", 2)
        assert item._card_image().page_caption() == "2 / 3"

    def test_so_do_the_other_presentation_params(self, env):
        graph, node, item, _path, _stack = env
        graph.set_param(node.id, "fit", "Fill")
        graph.set_param(node.id, "scale", 150)
        assert item._card_image().has_content()

    def test_picking_a_file_by_hand_still_wins(self, env, tmp_path):
        """The one param that does replace it — otherwise choosing a file on
        a node that has run would appear to do nothing."""
        graph, node, item, _path, _stack = env
        picked = tmp_path / "picked.pdf"
        picked.write_bytes(build_pdf([["just the one"]], "Picked"))
        graph.set_param(node.id, "path", str(picked))
        assert item._card_image().page_caption() == "1 / 1"


class TestTilePager:
    """The same pager on a dashboard tile — which is the surface that needs
    it most: a dashboard is the page somebody is handed, and its reader has
    no properties panel to type a page number into."""

    @pytest.fixture
    def env(self, qtbot, registry, tmp_path):
        from types import SimpleNamespace
        from PySide6.QtGui import QUndoStack
        from flograph.core import Graph
        from flograph.core.graph import Page, Tile
        from flograph.engine import ExecutionEngine
        from flograph.ui.dashboard.dashboard_scene import DashboardScene
        path = tmp_path / "three.pdf"
        path.write_bytes(build_pdf([["one"], ["two"], ["three"]], "Three"))
        graph = Graph()
        stack = QUndoStack()
        engine = ExecutionEngine(graph)
        graph.add_page(Page(id="p1", title="Board"))
        node = graph.add_node(registry.instantiate("flograph.viz.pdf_viewer"))
        node.params["path"] = str(path)
        node.dirty = False
        graph.add_tile("p1", Tile(id="t1", node_id=node.id, port="document",
                                  rect=(0.0, 0.0, 320.0, 444.0)))
        scene = DashboardScene(graph, engine, stack, "p1")
        item = scene.tile_items["t1"]
        paint_item(item)
        yield SimpleNamespace(graph=graph, node=node, item=item, stack=stack)
        scene.dispose()
        stack.clear()

    def test_the_tile_draws_chevrons(self, env):
        assert env.item._pager is not None

    def test_clicking_forward_turns_the_page(self, env):
        click(env.item, env.item._pager[1].center())
        assert env.node.params["page"] == 2
        assert env.item._card_image().page_caption() == "2 / 3"

    def test_clicking_back_turns_it_the_other_way(self, env):
        env.graph.set_param(env.node.id, "page", 3)
        click(env.item, env.item._pager[0].center())
        assert env.node.params["page"] == 2

    def test_it_stops_at_the_ends(self, env):
        click(env.item, env.item._pager[0].center())
        assert env.node.params["page"] == 1

    def test_turning_the_page_runs_nothing(self, env):
        """A slicer tick dirties the subgraph and asks for a re-run; this is
        a cosmetic param and must do neither."""
        click(env.item, env.item._pager[1].center())
        assert not env.node.dirty

    def test_paging_does_not_select_the_tile(self, env):
        click(env.item, env.item._pager[1].center())
        assert not env.item.isSelected()

    def test_a_locked_page_still_pages(self, env):
        """A locked dashboard is the finished one somebody was handed — the
        one most likely to be read rather than edited."""
        env.item.set_layout_locked(True)
        click(env.item, env.item._pager[1].center())
        assert env.node.params["page"] == 2

    def test_the_canvas_and_the_tile_agree(self, env):
        """One node, one page: the tile writes the same param the card reads,
        so a document cannot be on two different pages at once."""
        from flograph.ui.canvas import NodeGraphScene
        canvas = NodeGraphScene(env.graph, env.stack)
        card = canvas.node_items[env.node.id]
        click(env.item, env.item._pager[1].center())
        assert card._card_image().page_caption() == "2 / 3"

    def test_the_hovered_chevron_lights_up(self, env):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtWidgets import QGraphicsSceneHoverEvent
        event = QGraphicsSceneHoverEvent(QEvent.GraphicsSceneHoverMove)
        event.setPos(env.item._pager[1].center())
        env.item.hoverMoveEvent(event)
        assert env.item._pager_hover == 1
        event.setPos(QPointF(10, 60))
        env.item.hoverMoveEvent(event)
        assert env.item._pager_hover == 0
