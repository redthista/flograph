"""Read PDF

Read a PDF and hand back **one row per page**, so everything else in the
library works on it straight away: Filter Rows to the pages mentioning an
invoice number, String Manipulation to clean the text, Group By to count,
Show Table to read the result.

The **pages** table has `page` (1-based, as a reader would say it), `label`
(the page's printed label — "iv", "A-3" — which is not always the number),
`text`, `characters`, `words`, `width_pt` and `height_pt`. Turning off
*Extract text* leaves just the page inventory (`page`, `label`, and the two
sizes) and skips the extraction entirely, which is what you want when all
you need is "how many pages, how big".

The **document** port carries the file's metadata — title, author, subject,
keywords, creator, producer, created, modified, page count — for a Card, a
report header, or a Filter Rows over a folder's worth of documents.

**Payload** is the memory decision, and it is yours to make:

  • *Metadata only* (the default) puts the file's **path** on the wire. The
    document dict stays a few hundred bytes however large the PDF is, and
    the file is never read into memory whole — pdfium reads the parts of it
    that it needs, straight off disk.
  • *Metadata + bytes* adds `bytes` and a `data_uri` to the document dict.
    Choose it when the source was never a file (base64 out of an API or a
    database blob), when the file will have moved or changed by the time the
    flow runs again, or when something downstream wants to embed the
    document. The whole file then lives in the cache, so a 200MB scan costs
    200MB.

**Password** opens a protected document, and takes a `${variable}` so the
password can live in the project's `.env` rather than in the flow.

**Pages** limits the read to a range — `1-3, 7, 10-` — in the page numbers a
reader shows. Blank means every page.

A scanned document has no text layer, and pdfium cannot invent one: the text
comes back empty and the node says so in the log rather than quietly handing
you blank rows. OCR is a separate job this node does not do.

Connect a string to **path_input** to supply the file at run time — a
non-empty value there wins over the *PDF file* parameter, and a `data:` URI
or a base64 blob works there just as a path does.
"""
NODE = {
    "label": "Read PDF",
    "category": "IO",
    "version": "1.0",
    "inputs": [("path_input", "string", {"optional": True})],
    "outputs": [("pages", "dataframe"), ("document", "object")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "PDF file", "default": "",
     "placeholder": "file path, data: URI, or base64"},
    {"name": "password", "type": "string", "label": "Password", "default": "",
     "placeholder": "none, or ${pdf_password}"},
    {"name": "pages", "type": "string", "label": "Pages", "default": "",
     "placeholder": "all, e.g. 1-3, 7, 10-"},
    {"name": "extract_text", "type": "bool", "label": "Extract text",
     "default": True},
    {"name": "skip_empty", "type": "bool", "label": "Skip pages with no text",
     "default": False},
    {"name": "payload", "type": "choice", "label": "Payload",
     "options": ["Metadata only", "Metadata + bytes"],
     "default": "Metadata only"},
]


def run(ctx, path_input=None):
    import pandas as pd

    from flograph.core.pdfsource import resolve_source
    from flograph import pdfdoc

    p = ctx.params
    source = (path_input.strip()
              if isinstance(path_input, str) and path_input.strip()
              else str(p.get("path", "") or "").strip())
    if not source:
        raise ValueError(
            "no PDF selected — set 'PDF file' in the node's properties, or "
            "connect a non-empty string to 'path_input'")

    carry_bytes = p.get("payload", pdfdoc.PAYLOAD_LIGHT) == pdfdoc.PAYLOAD_HEAVY
    extract = bool(p.get("extract_text", True))
    # The light payload never reads the file whole — see core.pdfsource.
    data, path = resolve_source(source, need_bytes=carry_bytes)

    with pdfdoc.PdfDocument.open(data, path, str(p.get("password", "") or "")) as doc:
        wanted = pdfdoc.parse_page_range(p.get("pages", ""), doc.page_count)
        if not wanted:
            raise ValueError(
                f"the page range {p.get('pages')!r} selects no pages — this "
                f"document has {doc.page_count}")
        ctx.log(f"{path or 'document'}: {doc.page_count} page(s), "
                f"reading {len(wanted)}")

        rows = []
        empty = 0
        for index, page in enumerate(wanted):
            ctx.check_cancelled()
            ctx.progress(index / len(wanted))
            width, height = doc.page_size(page)
            row = {"page": page + 1, "label": doc.page_label(page),
                   "width_pt": round(width, 2), "height_pt": round(height, 2)}
            if extract:
                text = doc.page_text(page)
                if not text.strip():
                    empty += 1
                    if p.get("skip_empty", False):
                        continue
                row["text"] = text
                row["characters"] = len(text)
                row["words"] = len(text.split())
            rows.append(row)

        payload = pdfdoc.document_payload(doc, source, data, carry_bytes)
        if extract and empty == len(wanted):
            ctx.log("no text layer on any page read — this looks like a "
                    "scanned document, which needs OCR rather than extraction")
        elif empty:
            ctx.log(f"{empty} page(s) had no text layer")

    columns = ["page", "label", "width_pt", "height_pt"]
    if extract:
        columns += ["text", "characters", "words"]
    # Built with an explicit column list so an empty read still has the
    # schema every downstream node was wired against.
    table = pd.DataFrame(rows, columns=columns)
    ctx.progress(1.0)
    ctx.log(f"{len(table)} row(s)"
            + (f", {payload['bytes'] and len(payload['bytes']) or 0:,} bytes "
               "carried" if carry_bytes else ", path only"))
    return {"pages": table, "document": payload}
