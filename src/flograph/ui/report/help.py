"""The report reference behind the toolbar's "?" — everything you can
write in a report body, in one place.

The counterpart to the spreadsheet's fx button, and non-modal for the same
reason: it is read *while* writing, so it has to sit open beside the
editor rather than blocking it.

The syntax is small enough that this is the whole of it. Anything added to
the body language belongs here on the same commit — a reference that is
only mostly true is worse than none, because it is the thing people check
instead of experimenting.
"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout

from flograph.core.page_setup import FIELDS


def reference_html() -> str:
    fields = "".join(
        f"<tr><td><code>{token}</code></td><td>{what}</td></tr>"
        for token, what in FIELDS)
    return f"""
<h3>Embedding what the flow made</h3>
<p>A report is ordinary <b>markdown</b>. To place something the flow
produced, name it:</p>
<table cellspacing="0" cellpadding="4">
<tr><td><code>![[Sales Chart]]</code></td>
    <td>that node's output, wherever it is on the canvas</td></tr>
<tr><td><code>![[Summary|table]]</code></td>
    <td>a particular output <b>port</b> of it</td></tr>
<tr><td><code>![[Chart|width=50%]]</code></td>
    <td>half the width of the text column</td></tr>
<tr><td><code>![[Chart|width=280]]</code></td>
    <td>280 points wide, whatever the paper</td></tr>
<tr><td><code>![[Chart|figure|width=60%]]</code></td>
    <td>a port <i>and</i> a width</td></tr>
</table>
<p><b>Width is the answer to "the chart went onto the next page".</b> A
chart is placed at its full size, so one that will not fit in what is left
of the page starts a new one and leaves a gap. Sizing it down to
<code>60%</code> or so fits it under the heading it belongs with. (Making a
chart shrink itself into the space left is not something Qt's layout can
do — it is on the list, via the HTML export.)</p>
<p>Use <b>Insert embed &#9662;</b> to pick from the nodes that have
actually produced something — it also avoids typos in a label.</p>
<p>What an embed becomes depends on what arrives: a <b>chart</b> is placed
as a picture, a <b>table</b> as a table, a <b>number</b> inline in your
sentence, and a <b>string as markdown</b> — so prose composed in a Python
Script node drops straight in, headings and all. A <b>list</b> of charts
renders as a stack, which is how one embed becomes one chart per region.</p>
<p>Naming a <b>Report card</b> renders that card's contents onto the page —
charts, tables and all — rather than reproducing its source text.</p>
<p>An embed that resolves to nothing says so <i>on the page</i> and in the
warning strip above, rather than leaving a silent gap.</p>

<h3>Markdown</h3>
<p><code># Heading</code>, <code>## Subheading</code>,
<code>**bold**</code>, <code>*italic*</code>, <code>`code`</code>,
<code>&gt; quote</code>, <code>- bullet</code>, <code>1. numbered</code>,
tables, and <code>---</code> for a rule. Written on one line, an embed
renders <b>inline</b> in the sentence; on a line of its own it becomes a
block.</p>

<h3>Page breaks</h3>
<p>Start a new page with any of these, on a line of its own:</p>
<p><code>\\pagebreak</code> &nbsp; <code>\\newpage</code> &nbsp;
<code>&lt;!-- pagebreak --&gt;</code></p>
<p>Breaks are applied <b>after</b> embeds resolve, so a node that returns
markdown can force its own — one section per region, a page each.</p>

<h3>Page setup</h3>
<p><b>Page Setup&#8230;</b> sets the paper size, orientation and margins, an
optional <b>cover page</b>, and running <b>headers and footers</b>. The
preview shows the real pages, so what you see is what prints.</p>
<p>Header, footer and cover text may use these fields:</p>
<table cellspacing="0" cellpadding="4">{fields}</table>
<p>So a footer of <code>Page {{page}} of {{pages}}</code> reads
"Page 3 of 11". An unknown field is left on the page as written, so a typo
shows rather than disappearing.</p>

<h3>Reading the preview</h3>
<p>The preview shows the real pages. <b>Ctrl+wheel</b> zooms; plain wheel
scrolls. The <b>&#9646;&#9646;</b> button lays the pages out left-to-right
and wrapping instead of in one column — the contact sheet, for seeing where
everything falls at once.</p>

<h3>Getting it out</h3>
<p><b>Export PDF&#8230;</b> prints exactly the pages in the preview.
<b>Save HTML&#8230;</b> writes one self-contained file with the pictures
inside it, so it travels as a single attachment and still works when
moved.</p>
<p>The two are not the same document. The PDF is the preview, page for
page. The HTML is one continuous page set to the same paper size and
margins, which a browser then repaginates when <i>it</i> prints — and it
can do one thing the PDF cannot, which is avoid splitting a chart across a
page break. Use the PDF when the pages matter and the HTML when the
screen does.</p>
<p>Both are also on a <b>Report card's</b> right-click menu on the canvas,
along with <b>Open in Browser</b>.</p>

<h3>Handing it over</h3>
<p>Right-click the page tab and tick <b>Locked</b> to hide the editor and
this toolbar, leaving the document on its own. Locking hides the furniture,
not the controls — slicers still filter and tables still take typing. Page
Setup and Export PDF move onto that tab menu while it is locked.</p>
"""


class ReportHelpDialog(QDialog):
    """Non-modal so it can stay open beside the report being written."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Writing a report")
        self.setModal(False)
        self.resize(600, 620)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(reference_html())
        layout.addWidget(browser)
