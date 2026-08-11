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

This is not the Jinja/CSS export from ideas.md chunk B. That one owns the
*layout* — real page rules, running elements, interactive Plotly. This
takes Qt's own HTML as it comes and only fixes the images, which is why it
fits in a page and needs no template.
"""
from __future__ import annotations

import base64
import re

#: Qt writes its images as <img src="embed:0" ...>. Matched with the quotes
#: so that replacing index 1 cannot also hit the start of index 10.
_SRC = 'src="{}"'


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


def report_html(rendered, title: str = "") -> str:
    """`rendered` as a standalone HTML document.

    An animation is written out as the file it arrived as, so a GIF that
    moves on the canvas moves in the browser too — the QImage beside it is
    only ever the poster frame, which is all paper can take.
    """
    html = rendered.document.toHtml()
    for index, image in enumerate(rendered.images):
        payload = rendered.animations.get(index)
        mime = _animation_mime(payload) if payload else None
        uri = _data_uri(payload, mime) if mime else _image_uri(image)
        if uri is None:
            continue
        html = html.replace(_SRC.format(f"embed:{index}"), _SRC.format(uri))
    return _titled(html, title)


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
