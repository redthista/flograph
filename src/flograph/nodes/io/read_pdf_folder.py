"""Read PDF (Folder)

Read every PDF in a folder and stack them into one table — one row per page,
with a `file` column saying which document each page came from. A folder of
invoices, statements or reports becomes a table you can Filter, Group By and
chart like any other.

Two outputs:

  • **pages** — `file`, `page`, `label`, `text`, `characters`, `words`,
    `width_pt`, `height_pt`. Turning off *Extract text* leaves the page
    inventory without the text columns, which turns a folder of 500 scans
    into a page count in about a second.
  • **documents** — one row per file: `file`, `path`, `pages`, `title`,
    `author`, `subject`, `keywords`, `creator`, `producer`, `created`,
    `modified`, `has_text`, `error`. This is the one to Show Table first: it
    is where you see that three files are password protected and one is a
    scan with no text in it.

**Files that fail do not stop the read.** A password-protected or corrupt
document gets a row in **documents** with its `error` filled in and no pages
in **pages**, and the log names it. A folder read that dies on file 340 of
500 helps nobody. Set *Stop on first error* if you would rather it did.

**Payload** is the memory decision, and it is yours to make:

  • *Metadata only* (the default) keeps paths on the wire. Nothing is read
    into memory whole; the table stays small however large the folder is.
  • *Metadata + bytes* adds `bytes` and `data_uri` columns to **documents**,
    which means the entire folder is held in memory — and, since a data URI
    is base64, at roughly 2.3x the folder's size on disk. It is the right
    choice for a handful of documents you want to embed or re-emit, and the
    wrong one for a directory of scans. The node logs the total so the cost
    is never a surprise.

**Include / exclude patterns** are comma-separated globs matched against file
names: include keeps only what matches (blank = keep everything), exclude
then drops what matches.

**Max pages per file** caps a runaway document — a 4,000-page appendix in a
folder of two-page letters — at a number you choose. 0 reads all of them.

Connect a string to **path_input** to supply the folder at run time.
"""
NODE = {
    "label": "Read PDF (Folder)",
    "category": "IO",
    "inputs": [("path_input", "string", {"optional": True})],
    "outputs": [("pages", "dataframe"), ("documents", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "folder_open", "label": "Folder", "default": "",
     "placeholder": "folder holding the PDF files"},
    {"name": "password", "type": "string", "label": "Password", "default": "",
     "placeholder": "none, or ${pdf_password}"},
    {"name": "include_pattern", "type": "string", "label": "Include patterns",
     "default": "", "placeholder": "globs, e.g. invoice_*.pdf, *2026*"},
    {"name": "exclude_pattern", "type": "string", "label": "Exclude patterns",
     "default": "", "placeholder": "globs, e.g. *draft*, *copy*"},
    {"name": "extract_text", "type": "bool", "label": "Extract text",
     "default": True},
    {"name": "skip_empty", "type": "bool", "label": "Skip pages with no text",
     "default": False},
    {"name": "max_pages", "type": "int", "label": "Max pages per file (0 = all)",
     "default": 0, "min": 0},
    {"name": "payload", "type": "choice", "label": "Payload",
     "options": ["Metadata only", "Metadata + bytes"],
     "default": "Metadata only"},
    {"name": "stop_on_error", "type": "bool", "label": "Stop on first error",
     "default": False},
    {"name": "parallel_files", "type": "int", "label": "Files at once (0 = auto)",
     "default": 0, "min": 0},
]

EXTENSIONS = (".pdf",)


def run(ctx, path_input=None):
    import os

    import pandas as pd

    from flograph import folders, pdfdoc
    from flograph.core.pdfsource import resolve_source

    p = ctx.params
    folder = (path_input.strip()
              if isinstance(path_input, str) and path_input.strip()
              else str(p.get("path", "") or "").strip())
    if not folder:
        raise ValueError(
            "no folder selected — set 'Folder' in the node's properties, or "
            "connect a non-empty string to 'path_input'")

    include, exclude = p.get("include_pattern", ""), p.get("exclude_pattern", "")
    files = folders.discover(folder, EXTENSIONS, include, exclude)
    folders.require_files(
        files, folder, EXTENSIONS,
        bool(folders.patterns(include) or folders.patterns(exclude)))

    password = str(p.get("password", "") or "")
    carry_bytes = p.get("payload", pdfdoc.PAYLOAD_LIGHT) == pdfdoc.PAYLOAD_HEAVY
    extract = bool(p.get("extract_text", True))
    skip_empty = bool(p.get("skip_empty", False))
    max_pages = int(p.get("max_pages", 0) or 0)
    stop_on_error = bool(p.get("stop_on_error", False))

    def read_one(path):
        """One file -> (page rows, document row). Runs on a worker thread."""
        name = os.path.basename(path)
        try:
            data, resolved = resolve_source(path, need_bytes=carry_bytes)
            with pdfdoc.PdfDocument.open(data, resolved, password) as doc:
                count = doc.page_count
                wanted = range(min(count, max_pages) if max_pages else count)
                rows = []
                for page in wanted:
                    width, height = doc.page_size(page)
                    row = {"file": name, "page": page + 1,
                           "label": doc.page_label(page),
                           "width_pt": round(width, 2),
                           "height_pt": round(height, 2)}
                    if extract:
                        text = doc.page_text(page)
                        if skip_empty and not text.strip():
                            continue
                        row["text"] = text
                        row["characters"] = len(text)
                        row["words"] = len(text.split())
                    rows.append(row)
                record = {"file": name,
                          **pdfdoc.document_payload(doc, path, data, carry_bytes),
                          "has_text": doc.has_text(), "error": ""}
                record.pop("source", None)
                record.pop("mime", None)
                return rows, record
        except Exception as exc:
            if stop_on_error:
                raise
            # A named failure in the documents table, not a dead run — and
            # carrying every column the successful rows have, so one bad file
            # does not turn the metadata columns into a field of NaN.
            blank: dict = {"bytes": None, "data_uri": None} if carry_bytes else {}
            blank.update(dict.fromkeys(
                ("title", "author", "subject", "keywords", "creator",
                 "producer", "created", "modified"), ""))
            return [], {"file": name, "path": path, "pages": 0, **blank,
                        "has_text": False, "error": str(exc)}

    workers = folders.worker_count(p.get("parallel_files", 0), "pdfium",
                                   len(files))
    ctx.log(f"{len(files)} PDF(s) in {folder}"
            + (f", {workers} at a time" if workers > 1 else ""))

    page_rows, doc_rows, failed = [], [], 0
    for _path, (rows, record) in folders.read_files(ctx, files, read_one,
                                                    workers):
        page_rows.extend(rows)
        doc_rows.append(record)
        if record.get("error"):
            failed += 1
            ctx.log(f"    skipped: {record['error']}")

    page_columns = ["file", "page", "label", "width_pt", "height_pt"]
    if extract:
        page_columns += ["text", "characters", "words"]
    pages = pd.DataFrame(page_rows, columns=page_columns)
    documents = pd.DataFrame(doc_rows)
    if not carry_bytes:
        # Both keys exist in every payload; without the heavy option they are
        # None on every row, and a column of None helps nobody.
        documents = documents.drop(columns=["bytes", "data_uri"],
                                   errors="ignore")

    ctx.progress(1.0)
    scanned = int((~documents.get("has_text", pd.Series(dtype=bool))
                   .fillna(False)).sum()) - failed if len(documents) else 0
    ctx.log(f"{len(pages)} page(s) from {len(files) - failed} document(s)"
            + (f", {failed} failed" if failed else "")
            + (f", {scanned} with no text layer" if scanned > 0 else ""))
    if carry_bytes and "bytes" in documents.columns:
        carried = int(documents["bytes"].dropna().map(len).sum())
        ctx.log(f"carrying {carried:,} bytes of document data")
    return {"pages": pages, "documents": documents}
