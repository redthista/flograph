"""Save Report

Save one of the project's report pages to a file whenever this node runs —
as HTML (the web version, one self-contained file with its pictures inside)
or as PDF (the paper version, laid out by the page's Page Setup). The same
file **Save HTML…** and **Export PDF…** on the report page write, without
anyone clicking.

**Report** picks the page. Every chart, table or number the page embeds
becomes something this node waits for: it runs after them, and again
whenever one of them — or the page's text — changes. If one of them fails,
the report is not saved, rather than being saved with a hole in it —
unless **If the report has errors** says to save anyway.

**Save to** may hold these, filled in when the node runs:

    {page}       the page's title
    {date}       today, as 2026-09-24
    {time}       the time, as 14-05-09
    {datetime}   both

so `reports/{page} {date}.pdf` keeps one file a day. `${name}` flow
variables work here too. Leave off the extension and the format's is added.

**If the file exists**: Overwrite it, Add a number (`report (2).html`), or
Fail — which stops before anything is drawn.

**If the report has errors**: Don't save (the default) fails the node
when anything the page embeds failed, is out of date, or cannot be found or
drawn — the same problems the report page shows. Save anyway writes the
file with the gaps marked, and lists each one in the node's log.

**Outputs.** `path` is the file written, for a node that mails or uploads it.
`html` is the report as one HTML page when **Output the HTML** is ticked —
for either format, so a PDF run can still hand the web version on. With it
ticked, **Save to** may be left empty to produce the HTML without writing a
file at all.

Reports are drawn by the flograph window, so a headless run (`flograph run`)
cannot save one; the node fails there and says so.
"""
NODE = {
    "label": "Save Report",
    "category": "IO",
    "version": "1.0",
    "reads_report": "page",
    "inputs": [],
    "outputs": [("path", "string"), ("html", "string")],
}
PARAMS = [
    {"name": "page", "type": "page_ref", "label": "Report", "default": "",
     "ref_kind": "report"},
    {"name": "format", "type": "choice", "label": "Format",
     "options": ["HTML", "PDF"], "default": "HTML"},
    {"name": "path", "type": "file_save", "label": "Save to", "default": "",
     "placeholder": "e.g. reports/{page} {date}.html"},
    {"name": "if_exists", "type": "choice", "label": "If the file exists",
     "options": ["Overwrite", "Add a number", "Fail"],
     "default": "Overwrite"},
    {"name": "create_dirs", "type": "bool", "label": "Create folders",
     "default": True},
    {"name": "if_errors", "type": "choice", "label": "If the report has errors",
     "options": ["Don't save", "Save anyway"], "default": "Don't save"},
    {"name": "output_html", "type": "bool", "label": "Output the HTML",
     "default": False},
]


def run(ctx):
    from flograph.engine.report_export import export

    p = ctx.params
    want_html = bool(p.get("output_html"))
    result = export(ctx, p.get("page") or "", p.get("format") or "HTML",
                    p.get("path") or "", p.get("if_exists") or "Overwrite",
                    bool(p.get("create_dirs")), want_html,
                    p.get("if_errors") == "Save anyway")
    for problem in dict.fromkeys(result.problems):
        ctx.log(f"warning: {problem}")
    if result.path:
        ctx.log(f"saved {result.path}")
    return {"path": result.path, "html": result.html if want_html else ""}
