"""PDF Viewer

Show a page of a PDF on the canvas — and on a dashboard page, where a
contract, a policy schedule or last month's report can sit beside the
numbers that came out of it.

Three ways to get one:

  • drag a PDF file from the file manager onto the canvas,
  • drop this node and pick a file in "PDF file",
  • wire something into the **source** port — a path, a `data:` URI, a
    base64 string, or the `document` output of Read PDF, which is the usual
    way: read a folder, filter to the document you care about, show it.

The card draws straight from the source, so a document picked here appears
without running the graph, and turning the page never runs it either —
click the chevrons either side of "2 / 12" at the bottom of the card, or set
**Page** here, whichever is to hand. The page is rendered at the size the
card is actually drawn at, so a 400-page report on the canvas costs one page
of pixels and reads the file from disk as it needs it.

**Show page number** is what puts that pager on the card; turn it off for a
bare page, and turn the pages from **Page**.

Running the node emits the same **document** dict Read PDF produces —
metadata, page count, and optionally the bytes — so a viewer can sit
mid-flow rather than only at the end.

**Payload** is the memory decision, and it is yours to make: *Metadata only*
(the default) puts the file's path on the wire and keeps the dict tiny;
*Metadata + bytes* adds `bytes` and a `data_uri` for anything downstream
that wants to embed the document, at the cost of the whole file living in
the cache.

**Password** opens a protected document, and takes a `${variable}` so the
password can live in the project's `.env` rather than in the flow.

This is a viewer, not a reader: it draws pages. Use **Read PDF** when you
want the text as a table.
"""

# The "card": "pdf" marker is what gives this node the rendered page — it
# travels with the code, so a copy saved as a user node keeps the view.
NODE = {
    "label": "PDF Viewer",
    "category": "Viz",
    "version": "1.0",
    "card": "pdf",
    # Optional, and typed 'any' so it takes both a plain path string and the
    # `document` dict Read PDF emits.
    "inputs": [("source", "any", {"optional": True})],
    "outputs": [("document", "object")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "PDF file", "default": "",
     "placeholder": "file path, data: URI, or base64"},
    # Cosmetic: run() never reads it — the page is rendered by the card, from
    # the document this node already opened, so turning the page costs no
    # run. The card's own chevrons write this same param.
    {"name": "page", "type": "int", "label": "Page", "default": 1, "min": 1,
     "max": 10000, "cosmetic": True},
    {"name": "password", "type": "string", "label": "Password", "default": "",
     "placeholder": "none, or ${pdf_password}"},
    {"name": "fit", "type": "choice", "label": "Fit",
     "options": ["Fit", "Fill", "Stretch", "Original size"], "default": "Fit"},
    # Cosmetic for the same reason as Page.
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
    # Also the card's pager: the chevrons live either side of this caption.
    {"name": "show_page_number", "type": "bool", "label": "Show page number",
     "default": True, "cosmetic": True},
    {"name": "background", "type": "bool", "label": "Card background",
     "default": True},
    {"name": "payload", "type": "choice", "label": "Payload",
     "options": ["Metadata only", "Metadata + bytes"],
     "default": "Metadata only"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 320, "min": 60, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 420, "min": 60, "max": 1600, "cosmetic": True},
]


def run(ctx, source=None):
    # Imported here, not at the top: the canvas card resolves sources with
    # these same modules, so a path, a data: URI and a base64 blob can never
    # mean one thing to the node and another to the document on screen.
    from flograph.core.pdfsource import resolve_source
    from flograph import pdfdoc

    p = ctx.params
    # A wired `document` dict is the commonest input — take its path rather
    # than making the user unpack it with an Expression node first.
    if isinstance(source, dict):
        source = source.get("source") or source.get("path") or ""
    raw = str(source if source else p.get("path", "") or "").strip()
    if not raw:
        raise ValueError(
            "no PDF given — set 'PDF file', drag a PDF onto the canvas, or "
            "wire in a path, a data: URI or a document from Read PDF")

    carry_bytes = p.get("payload", pdfdoc.PAYLOAD_LIGHT) == pdfdoc.PAYLOAD_HEAVY
    data, path = resolve_source(raw, need_bytes=carry_bytes)
    with pdfdoc.PdfDocument.open(data, path, str(p.get("password", "") or "")) as doc:
        payload = pdfdoc.document_payload(doc, raw, data, carry_bytes)
        title = payload.get("title") or path or "document"
        ctx.log(f"{title}: {doc.page_count} page(s)")
    return {"document": payload}
