"""A rendered report as one self-contained HTML file.

What this is for: a report *card* has no page, so it has no toolbar, so
until now there was no way to get one in front of anyone who isn't looking
at the canvas. "Open in Browser" is that way, and it is the same deal
webview nodes already get (ui/browser.py) — a full screen, find-in-page,
zoom, print, and a URL you can leave open beside the app.

The one thing that has to happen here is the pictures. A rendered report
holds its images as *document resources* under an "embed:N" URL, which
means nothing at all outside this process: written out as-is, every chart
in the file would be a broken-image icon. So they are inlined as data URIs,
which also makes the file one thing you can mail rather than a page plus a
folder.

This is not the Jinja/CSS export shelved as ideas_archived.md item 8. That
one owns the *layout* — real page rules, running elements, interactive
Plotly. This
takes Qt's own HTML as it comes and only fixes the images, which is why it
fits in a page and needs no template.
"""
from __future__ import annotations

import base64
import re

#: Qt writes its images as <img src="embed:0" ...>. Matched with the quotes
#: so that replacing index 1 cannot also hit the start of index 10.
_SRC = 'src="{}"'


# Starter styles are deliberately ordinary browser CSS. They are inserted
# into the page's custom stylesheet, so a user can edit the result rather
# than being locked into a theme.
CSS_TEMPLATES = {
    "Clean": """body {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.5;
  color: #1f2937;
  background: #f3f4f6;
}
body > * { max-width: 100%; }
h1, h2, h3 { color: #111827; }
h1 { border-bottom: 2px solid #2563eb; padding-bottom: 0.3em; }
h2 { margin-top: 1.6em; color: #1d4ed8; }
table { width: 100%; margin: 1.2em 0; }
table thead,
table thead tr,
table thead th,
table thead td {
  background-color: #1d4ed8 !important;
  color: #ffffff !important;
}
.flograph-table thead th *, .flograph-table thead td *,
table thead td p, table thead td span {
  color: #ffffff !important;
  background-color: #1d4ed8 !important;
}
.flograph-table tr:nth-child(even) { background: #eff6ff; }
td, th { padding: 7px 9px; }
img { display: block; margin: 1.5em auto; }
""",
    "Editorial": """body {
  font-family: Georgia, "Times New Roman", serif;
  line-height: 1.65;
  color: #292524;
  background: #fafaf9;
}
h1, h2, h3 { font-family: system-ui, sans-serif; color: #292524; }
h1 { font-size: 2.2em; letter-spacing: -0.02em; }
h2 { margin-top: 2em; border-bottom: 1px solid #d6d3d1; padding-bottom: 0.2em; }
blockquote { border-left: 4px solid #a16207; background: #fefce8; padding: 0.7em 1em; }
table { width: 100%; margin: 1.5em 0; }
table thead,
table thead tr,
table thead th,
table thead td {
  background-color: #44403c !important;
  color: #ffffff !important;
}
.flograph-table thead th *, .flograph-table thead td *,
table thead td p, table thead td span {
  color: #ffffff !important;
  background-color: #44403c !important;
}
.flograph-table tr:nth-child(even) { background: #f5f5f4; }
td, th { padding: 8px 10px; }
img { display: block; margin: 2em auto; }
""",
    "Slate": """body {
  font-family: Inter, system-ui, sans-serif;
  line-height: 1.5;
  color: #e2e8f0;
  background: #0f172a;
}
h1, h2, h3 { color: #f8fafc; }
h1 { border-bottom: 2px solid #38bdf8; padding-bottom: 0.3em; }
h2 { color: #7dd3fc; margin-top: 1.6em; }
a { color: #67e8f9; }
blockquote { color: #fde68a; border-left-color: #f59e0b; }
table { width: 100%; margin: 1.2em 0; }
.flograph-table { background: #1e293b; }
table thead,
table thead tr,
table thead th,
table thead td {
  background-color: #0369a1 !important;
  color: #ffffff !important;
}
.flograph-table thead th *, .flograph-table thead td *,
table thead td p, table thead td span {
  color: #ffffff !important;
  background-color: #0369a1 !important;
}
.flograph-table tbody td:not([bgcolor]),
table tbody td:not([bgcolor]),
table > tr > td[style*="border-top"]:not([bgcolor]):not([style*="background"]) {
  background-color: #ffffff !important;
  color: #1f2937 !important;
}
.flograph-table tbody td:not([bgcolor]) *,
table tbody td:not([bgcolor]) *,
table > tr > td[style*="border-top"]:not([bgcolor]):not([style*="background"]) * {
  color: #1f2937 !important;
}
.flograph-table tbody tr:nth-child(even) td:not([bgcolor]),
table tbody tr:nth-child(even) td:not([bgcolor]),
table > tr:nth-of-type(odd) > td[style*="border-top"]:not([bgcolor]):not([style*="background"]) {
  background-color: #f1f5f9 !important;
}
/* Data bars use a nested layout table. Its value cell must inherit the
   outer row's colour; only the track itself should have a light background. */
table table td:not([bgcolor]) {
  background-color: transparent !important;
}
table table > tr > td:first-child {
  background-color: inherit !important;
}
.flograph-table tr:nth-child(even) { background: #273449; }
td, th { padding: 7px 9px; }
""",
}


def _data_uri(payload: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


def _animation_mime(payload: bytes) -> "str | None":
    """The type of an encoded animation, from its first bytes.

    Only the two formats the Image node treats as animated, because those
    are the only ones that reach here — anything else was rasterised to a
    QImage long before this point.
    """
    if payload[:3] == b"GIF":
        return "image/gif"
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    return None


def _image_uri(image) -> "str | None":
    """One QImage as a PNG data URI. PNG rather than JPEG: a report's
    pictures are charts and tables, where a compression artefact around a
    thin line is exactly what you would notice."""
    from PySide6.QtCore import QBuffer

    # QBuffer's *own* byte array, not one passed to the constructor: a
    # QByteArray handed in is a Python temporary, and the buffer keeps a
    # pointer to it after it has been collected — which segfaults rather
    # than failing.
    buffer = QBuffer()
    buffer.open(QBuffer.WriteOnly)
    try:
        if not image.save(buffer, "PNG"):
            return None
        return _data_uri(bytes(buffer.data()), "image/png")
    finally:
        buffer.close()


def page_style(setup) -> str:
    """CSS that puts the report on the paper it was set up for.

    Not the Jinja/CSS export shelved as ideas_archived.md item 8 — that
    one owns the layout and can do running headers, counters and
    interactive Plotly.
    This is the cheap half: the same page size and margins, and a body
    that measures the same as the PDF's text column, so a chart sized for
    the page is the same fraction of the width in both. Without it the
    HTML was a browser-default wall of text at whatever width the window
    happened to be, which is why it read as a different document.

    `@page` also makes the browser's own Print produce the right paper,
    which is the one thing this export can offer that the PDF cannot: a
    page break that avoids splitting a chart (`break-inside: avoid`), the
    half of A3 Qt has no answer for.
    """
    from flograph.core.page_setup import page_css
    width, _height = setup.body_mm()
    return f"""
{page_css(setup)}
body {{
  margin: 0 auto;
  padding: 24px 16px;
  max-width: {width:g}mm;
  background: #ffffff;
  color: #111111;
}}
img {{ max-width: 100%; height: auto; }}
table {{ border-collapse: collapse; }}
@media print {{
  body {{ padding: 0; max-width: none; }}
  /* What the Qt export cannot express: keep a chart whole. */
  img, table, pre, blockquote {{ break-inside: avoid; page-break-inside: avoid; }}
  h1, h2, h3 {{ break-after: avoid; page-break-after: avoid; }}
}}
"""


def report_html(rendered, title: str = "", setup=None,
                auto_refresh: bool = False, custom_css: str = "") -> str:
    """`rendered` as a standalone HTML document.

    An animation is written out as the file it arrived as, so a GIF that
    moves on the canvas moves in the browser too — the QImage beside it is
    only ever the poster frame, which is all paper can take.

    `setup` puts it on the same paper as the PDF (see page_style); without
    one the page is Qt's own HTML at whatever width the window is.
    `auto_refresh` is for the throwaway copy behind Open in Browser only.
    """
    html = rendered.document.toHtml()
    for index, image in enumerate(rendered.images):
        payload = rendered.animations.get(index)
        mime = _animation_mime(payload) if payload else None
        uri = _data_uri(payload, mime) if mime else _image_uri(image)
        if uri is None:
            continue
        html = html.replace(_SRC.format(f"embed:{index}"), _SRC.format(uri))
    if setup is not None:
        html = _styled(html, page_style(setup))
    if custom_css:
        html = _styled(html, custom_css)
    if auto_refresh:
        html = _styled(html, "", head_extra=_AUTO_REFRESH)
    return _titled(html, title)


#: Injected only into the throwaway copy behind Open in Browser, never into
#: a file someone asked to keep. A meta refresh rather than anything
#: cleverer because a file:// page cannot fetch its own directory to poll
#: for changes — Chrome blocks it — so this is the one mechanism that works
#: with no server and no permissions. The script is what stops a reload
#: throwing away where you had scrolled to.
_AUTO_REFRESH = """
<meta http-equiv="refresh" content="2">
<script>
  addEventListener('beforeunload', function () {
    sessionStorage.setItem('flograph-scroll', String(window.scrollY));
  });
  addEventListener('load', function () {
    var at = sessionStorage.getItem('flograph-scroll');
    if (at) { window.scrollTo(0, parseInt(at, 10)); }
  });
</script>
"""


def _styled(html: str, css: str, head_extra: str = "") -> str:
    """Add a stylesheet (and anything else) to the document's head.

    Appended *after* Qt's own <style>, so these rules win on a tie —
    QTextDocument.toHtml writes a stylesheet of its own and this has to sit
    on top of it rather than under it.
    """
    block = (f"<style>{css}</style>" if css else "") + head_extra
    if not block:
        return html
    if re.search(r"</head>", html, re.IGNORECASE):
        return re.sub(r"</head>", block + "</head>", html, count=1,
                      flags=re.IGNORECASE)
    return block + html


def _titled(html: str, title: str) -> str:
    """Put `title` in the document's head — it is what the browser tab and
    Save As will say, and "Untitled" for every report exported would make a
    row of open tabs useless."""
    if not title:
        return html
    tag = f"<title>{_escape(title)}</title>"
    if re.search(r"<title>", html, re.IGNORECASE):
        return re.sub(r"<title>.*?</title>", tag, html,
                      count=1, flags=re.IGNORECASE | re.DOTALL)
    if re.search(r"<head[^>]*>", html, re.IGNORECASE):
        return re.sub(r"(<head[^>]*>)", r"\1" + tag, html,
                      count=1, flags=re.IGNORECASE)
    return tag + html


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))
