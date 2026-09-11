"""Opening a link someone wrote: in a Note, on a canvas card or a dashboard
tile, or in a report page's preview.

Web and mail links only. A note or a report is text someone else wrote,
and a `file:` link in it should not be one click from running something.
A `page:` link is not handled here: it goes to a page of this project,
which the window decides (`MainWindow._follow_page_link`).
"""
from __future__ import annotations

#: The schemes a written link may open in the system browser or mail client.
WEB_LINK_SCHEMES = {"http", "https", "mailto"}


def open_web_link(href: str) -> bool:
    """Open `href` if it is a web or mail link; say whether it was."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    if not href:
        return False
    url = QUrl(href)
    if not url.scheme():
        url = QUrl.fromUserInput(href)  # bare "example.com", "./file.pdf"
    if url.scheme().lower() not in WEB_LINK_SCHEMES:
        return False
    QDesktopServices.openUrl(url)
    return True
