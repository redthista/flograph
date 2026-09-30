"""A saved report web page reaches nothing off the machine.

The page is a file someone is emailed and opens on a train, behind a proxy,
or with no network at all, so everything it draws with has to be inside
it: Plotly inline, map outlines preloaded, the layout's and the live
tables' scripts, the theme, the icon. Nothing may come from a CDN, a font
service or anywhere else. (Tools ▸ Web Libraries is where a library is
*installed from*, once; a page never renders from one.)

A static scan, over a page that uses everything at once, under every
starter theme. plotly.js itself is left out: it carries URLs of its own
(the CDN it would fetch map outlines from, tile servers) which the page's
config turns off, and that config is checked here too.
"""
import re

import pandas as pd
import pytest

from flograph.core.web_layout import WebSettings
from flograph.ui.report import render as R
from flograph.ui.report.html import CSS_TEMPLATES, report_html
from flograph.ui.report.live import LIVE_CSS, LIVE_JS
from flograph.ui.report.web_layout import LAYOUT_CSS, LAYOUT_JS

#: Addresses: any scheme with //, or a protocol-relative //host.tld/.
URL_RE = re.compile(r"""\b(?:https?|wss?|ftp):(?://)?[^\s"'<>)]+"""
                    r"""|(?<![:\w/])//[a-z0-9-]+(?:\.[a-z0-9-]+)+/""", re.I)
#: Ways a script can open a connection.
API_RE = re.compile(r"\b(?:fetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon"
                    r"|EventSource|importScripts|serviceWorker|import\s*\()")
#: A tag that loads what it points at, pointing anywhere but in the page.
TAG_RE = re.compile(r"""<(?:script|link|img|iframe|source|video|audio|embed"""
                    r"""|object|image|use)\b[^>]*?\b(?:src|href|data|srcset)"""
                    r"""\s*=\s*["']?(?!data:|#|blob:)([^"'\s>]*)""", re.I)
#: CSS that loads: @import, and url() of anything not a data: URI.
CSS_LOAD_RE = re.compile(r"""@import|url\(\s*(?!["']?\s*(?:data:|#))""", re.I)
#: XML namespaces are names, never fetched.
NAMESPACES = ("http://www.w3.org/", "https://www.w3.org/")

BODY = """---
title: Offline
icon: 📈
---
# Sales review

Intro with a [link to a page](page:Other) and `![[code]]`.

## Charts

![[Chart|live]]

![[Map|live]]

## Tables

::: tabs Region
== Live
![[Sales|search]]
== Plain
![[Sales|width=90%]]
:::

::: details Method|open
| a | b |
|---|---|
| 1 | 2 |
:::
"""

WEB = WebSettings(sidebar="open", topbar=True, menus=True, split=True,
                  paged="headings", pager=True, width=1100, share_state=True)


def remote(text: str) -> list:
    """Everything in `text` that would reach off the machine."""
    found = [u for u in URL_RE.findall(text) if not u.startswith(NAMESPACES)]
    found += API_RE.findall(text)
    found += [t for t in TAG_RE.findall(text) if t]
    found += CSS_LOAD_RE.findall(text)
    return found


def without_plotly(html: str) -> str:
    """The page less the plotly.js bundle — the one script over 1 MB."""
    for m in re.finditer(r"<script\b[^>]*>(.*?)</script>", html, re.S):
        if len(m.group(1)) > 1_000_000:
            assert "plotly" in m.group(1)[:5000].lower()
            return html[:m.start()] + html[m.end():]
    return html


@pytest.fixture(scope="module")
def rendered(qapp):
    go = pytest.importorskip("plotly.graph_objects")
    values = {
        "Chart": go.Figure(go.Bar(x=["a", "b"], y=[1, 2])),
        "Map": go.Figure(go.Choropleth(locations=["FRA", "DEU"], z=[1, 2])),
        "Sales": pd.DataFrame({"region": ["n", "s"], "revenue": [3, 4]}),
    }
    mp = pytest.MonkeyPatch()
    mp.setattr(R._Resolver, "_table_style", lambda self, ref: ((), (), ()))
    mp.setattr(R._Resolver, "_table_totals", lambda self, ref: (None, None))
    try:
        yield R.render_body(BODY, lambda ref, port: (values[ref], None, None),
                            live=True)
    finally:
        mp.undo()


class TestTheScanItself:
    """The patterns catch what they are for — otherwise a clean page proves
    nothing."""

    @pytest.mark.parametrize("snippet", [
        '<script src="https://cdn.plot.ly/plotly.min.js"></script>',
        '<link rel="stylesheet" href="//fonts.googleapis.com/css">',
        '<img src="logo.png">',
        "@import url(theme.css);",
        "body { background: url('https://x.test/a.png') }",
        "fetch('/api')",
        "new WebSocket(u)",
        "navigator.sendBeacon(u, d)",
    ])
    def test_it_catches(self, snippet):
        assert remote(snippet)

    @pytest.mark.parametrize("snippet", [
        '<img src="data:image/png;base64,AAAA">',
        "a { background: url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E\") }",
        '<a href="#page=x">x</a>',
        "// a comment in a script",
    ])
    def test_it_lets_the_page_itself_through(self, snippet):
        assert not remote(snippet)


class TestASavedPage:
    def test_it_holds_what_it_draws_with(self, rendered):
        html = report_html(rendered, "t", web=WEB)
        assert len(html) - len(without_plotly(html)) > 1_000_000
        assert 'G["world_110m"]=' in html            # the map's outlines
        assert "fg-side" in html and "fg-table" in html

    @pytest.mark.parametrize("theme", ["(none)"] + sorted(CSS_TEMPLATES))
    def test_under_every_theme_it_reaches_nothing(self, rendered, theme):
        html = report_html(rendered, "t", web=WEB,
                           custom_css=CSS_TEMPLATES.get(theme, ""))
        assert remote(without_plotly(html)) == []

    def test_plotly_is_told_never_to_fetch_map_outlines(self, rendered):
        page = without_plotly(report_html(rendered, "t", web=WEB))
        assert 'topojsonURL: "flograph-map-outlines/"' in page
        # named in a comment saying so; never as an address
        assert not re.search(r"(?:https?:)?//cdn\.plot\.ly", page)

    def test_the_app_preview_loads_plotly_from_beside_the_page(self, rendered):
        from flograph.ui.report.web_preview import PREVIEW_PLOTLY
        assert not re.match(r"(?:[a-z]+:)?//", PREVIEW_PLOTLY, re.I)
        html = report_html(rendered, "t", web=WEB, plotly_src=PREVIEW_PLOTLY)
        # the one thing the preview loads is that local file
        assert remote(html) == [PREVIEW_PLOTLY]


@pytest.mark.parametrize("name, text", [
    ("LIVE_JS", LIVE_JS), ("LIVE_CSS", LIVE_CSS),
    ("LAYOUT_JS", LAYOUT_JS), ("LAYOUT_CSS", LAYOUT_CSS),
] + [(f"theme {n}", css) for n, css in sorted(CSS_TEMPLATES.items())])
def test_each_part_on_its_own(name, text):
    """Named, so a failure says which part brought the address in."""
    assert remote(text) == [], name
