"""Paint caching for widgets embedded in a scene (cards and tiles).

A QGraphicsProxyWidget repaints its whole widget — every ribbon button,
header section and cell — each time the view paints the area it covers, and
a pan paints all of it every frame. A NodeItem's own DeviceCoordinateCache
does not help: Qt caches an item's paint(), not its children's. Measured on
a canvas of Table cards (0.1.25): ~220-400 ribbon-button paints per pan
frame, and a dashboard tile drag repainted every tile on the page.

DeviceCoordinateCache on the proxy turns that into one blit per frame while
nothing inside changes. Anything that does change — a typed cell, a hover, a
caret — asks the proxy to update, which invalidates just that part of the
picture, so the widget stays live. A zoom re-renders it once at the new
scale, which keeps text sharp.

Web views (Plotly, web cards) are left uncached: Chromium draws into them
on its own schedule, and until that is shown to invalidate the picture
reliably a stale chart is worse than a slow one.
"""
from __future__ import annotations

from PySide6.QtGui import QGuiApplication, QPixmapCache
from PySide6.QtWidgets import QGraphicsItem, QGraphicsProxyWidget

#: tile content kinds that are, or may hold, a web view
UNCACHED_KINDS = frozenset({"plotly", "generic"})


def cache_proxy(proxy: QGraphicsProxyWidget, on: bool = True) -> None:
    proxy.setCacheMode(QGraphicsItem.DeviceCoordinateCache if on
                       else QGraphicsItem.NoCache)


#: bounds on the shared picture cache, in KB
PIXMAP_CACHE_MIN_KB = 64 * 1024
PIXMAP_CACHE_MAX_KB = 256 * 1024
#: screens' worth of 32-bit pixels the cache should hold
PIXMAP_CACHE_SCREENS = 3


def size_pixmap_cache() -> int:
    """Give every item cache in the app room to work; returns the limit (KB).

    Every DeviceCoordinateCache picture — each node, card and tile — lives
    in the one QPixmapCache, whose default is 10 MB. A busy canvas or
    dashboard is past that at once, and then the cache thrashes: each frame
    evicts the pictures the next frame needs, and every item repaints from
    scratch as if nothing were cached. Measured on a 24-tile dashboard
    (0.1.26): 488 ribbon-button paints per pan frame at 10 MB, 2 at 64 MB.

    Sized to the screens rather than to the machine: what is cached is what
    is on screen, so a few screens' worth of pixels is what the cache can
    ever usefully hold — 64 MB on a laptop, more on a 4K desk. Only ever
    raised: a limit already set higher is kept.
    """
    pixels = 0
    app = QGuiApplication.instance()
    for screen in (app.screens() if app is not None else ()):
        size = screen.size()
        ratio = screen.devicePixelRatio()
        pixels += int(size.width() * ratio) * int(size.height() * ratio)
    wanted = PIXMAP_CACHE_SCREENS * pixels * 4 // 1024
    wanted = max(PIXMAP_CACHE_MIN_KB, min(PIXMAP_CACHE_MAX_KB, wanted))
    if QPixmapCache.cacheLimit() < wanted:
        QPixmapCache.setCacheLimit(wanted)
    return QPixmapCache.cacheLimit()
