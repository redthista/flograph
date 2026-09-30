"""A report's web page given a shape: folding sections, tabs, a sidebar of
its headings, a bar across the top, and an address that says what is open.

The `:::` blocks arrive as token paragraphs (core/web_layout.py says why)
and are swapped here for the elements — <details>, and a tab bar over one
<section> per tab. Every heading and block gets an id, the same one every
time for the same text, because the ids are what a shared address names.

The rest is a script, and the page reads whole without it: every tab shown
one under another under its name, sections as their browser's own folding
<details>, headings in order. With it:

- **Tabs** show one part at a time; arrow keys move along the bar.
- **Sidebar** lists the headings down to the page's depth, folds by
  branch, follows the reading place, and hides behind a button. Whether a
  reader keeps it open is theirs (remembered in their browser); where it
  starts is the page's.
- **Top bar**: `links` jumps along the top-level sections of one long page;
  `pages` shows one of them at a time, like the pages of a site, with what
  comes before the first as a header on every one. Top level is the
  highest heading level used at least twice — a report with one `#` title
  and a `##` per region splits by region.
- **The address**: `#page=costs&tab.region=north&open=notes&at=q3` — the
  page, each tab not on its first part, each section not in its starting
  state, and the heading being read — kept up to date as the reader goes
  (replaceState; a new page of a `pages` site is a Back step). A plain
  `#heading` still works, and opens whatever hides it. Off with the page's
  **Keep the view in the address** setting.
- **Printing** shows everything: every tab, every page, sections open.
"""
from __future__ import annotations

import html as _html
import json
import re

from flograph.core.web_layout import BLOCK_P_RE, WebSettings, slug

_HEADING_RE = re.compile(r"<h([1-6])\b([^>]*)>(.*?)</h\1\s*>",
                         re.IGNORECASE | re.DOTALL)
_TAGS_RE = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return " ".join(_html.unescape(_TAGS_RE.sub("", fragment)).split())


def apply_layout(html: str, rendered, settings: "WebSettings | None" = None,
                 title: str = "") -> str:
    """`html` (a whole report page) with its blocks built and, when the page
    asks for any, its sidebar, top bar and address state switched on.

    A page with no block and default settings comes back unchanged, so a
    report that uses none of this saves exactly as it did before.
    """
    settings = settings or WebSettings()
    blocks = list(getattr(rendered, "blocks", None) or [])
    if not blocks and settings.is_default():
        return html
    used: set = set()
    html = _with_heading_ids(html, used)
    if blocks:
        html = _with_blocks(html, blocks, used)
    head = f"<style>{LAYOUT_CSS}{_width_css(settings.width)}</style>"
    config = {"sidebar": settings.sidebar, "depth": settings.depth,
              "navbar": settings.navbar, "share": settings.share_state,
              "title": title}
    # `</` can't close the script from inside a JSON string once escaped
    payload = json.dumps(config).replace("</", "<\\/")
    body = (f'<script type="application/json" id="fg-layout-config">'
            f"{payload}</script><script>{LAYOUT_JS}</script>")
    html = _before(html, "</head>", head)
    return _before(html, "</body>", body)


def _before(html: str, tag: str, block: str) -> str:
    at = html.lower().rfind(tag)
    if at == -1:
        return html + block if tag == "</body>" else block + html
    return html[:at] + block + html[at:]


def _with_heading_ids(html: str, used: set) -> str:
    def named(match: re.Match) -> str:
        level, attrs, inner = match.group(1), match.group(2), match.group(3)
        if re.search(r"\bid\s*=", attrs, re.IGNORECASE):
            return match.group(0)
        text = _text(inner)
        if not text:
            return match.group(0)
        ident = slug(text, used)
        return f'<h{level} id="{ident}"{attrs}>{inner}</h{level}>'
    return _HEADING_RE.sub(named, html)


def _with_blocks(html: str, blocks: list, used: set) -> str:
    ids = {}
    tab_ids = {}
    for number, block in enumerate(blocks):
        name = block.title or ("tabs" if block.kind == "tabs" else "section")
        ids[number] = slug(name, used)
        own: set = set()
        tab_ids[number] = [slug(tab, own) for tab in block.tabs]

    def built(match: re.Match) -> str:
        edge, number = match.group(1).lower(), int(match.group(2))
        if number >= len(blocks):
            return ""
        block = blocks[number]
        ident = ids[number]
        if block.kind == "details":
            if edge == "open":
                summary = _html.escape(block.title or "Details")
                state = "open" if block.open else "shut"
                return (f'<details class="fg-details" id="{ident}" '
                        f'data-fg-default="{state}"'
                        f'{" open" if block.open else ""}>'
                        f"<summary>{summary}</summary>"
                        f'<div class="fg-details-body">')
            if edge == "close":
                return "</div></details>"
            return ""
        # tabs
        if edge == "open":
            buttons = "".join(
                f'<button type="button" role="tab" data-tab="{tab_id}">'
                f"{_html.escape(name)}</button>"
                for name, tab_id in zip(block.tabs, tab_ids[number]))
            label = (f' aria-label="{_html.escape(block.title, quote=True)}"'
                     if block.title else "")
            return (f'<div class="fg-tabs" id="{ident}">'
                    f'<div class="fg-tabbar" role="tablist"{label}>'
                    f"{buttons}</div>")
        if edge == "tab":
            index = int(match.group(3) or 0)
            if index >= len(block.tabs):
                return ""
            name = _html.escape(block.tabs[index], quote=True)
            opening = "</section>" if index else ""
            return (f'{opening}<section class="fg-tab" role="tabpanel" '
                    f'data-tab="{tab_ids[number][index]}" '
                    f'data-title="{name}">')
        return ("</section>" if block.tabs else "") + "</div>"

    return BLOCK_P_RE.sub(built, html)


def _width_css(width: int) -> str:
    if not width:
        return ""
    return f"""
:root {{ --fg-width: {int(width)}px; }}
@media screen {{
  body {{ max-width: var(--fg-width); margin-left: auto !important;
         margin-right: auto !important; box-sizing: border-box; }}
}}
@media screen and (min-width: 900px) {{
  html.fg-side-on body {{
    margin-left: calc(var(--fg-side-w) +
      max(0px, (100vw - var(--fg-side-w) - var(--fg-width)) / 2)) !important;
  }}
}}
"""


LAYOUT_CSS = """
:root {
  --fg-accent: #7c6cf6;
  --fg-nav-bg: #ffffff;
  --fg-nav-ink: #1f2430;
  --fg-nav-muted: #6b7280;
  --fg-nav-line: #e3e5ea;
  --fg-nav-hover: rgba(124, 108, 246, 0.09);
  --fg-side-w: 264px;
  --fg-top-h: 0px;
  /* Qt sets the body a size smaller than the text it writes (every
     paragraph carries its own); a tab or a section's title matches the
     text, not the body */
  --fg-text-size: 11pt;
}
html.fg-has-top { --fg-top-h: 48px; }
[id] { scroll-margin-top: calc(var(--fg-top-h) + 14px); }

/* ---- folding sections */
details.fg-details {
  border: 1px solid var(--fg-nav-line); border-radius: 10px;
  margin: 14px 0; overflow: hidden;
}
details.fg-details > summary {
  cursor: pointer; list-style: none; display: flex; align-items: center;
  gap: 10px; padding: 10px 14px; font-weight: 600; user-select: none;
  font-size: var(--fg-text-size);
}
details.fg-details > summary::-webkit-details-marker { display: none; }
details.fg-details > summary::before {
  content: ""; width: 6px; height: 6px; flex: none;
  border-right: 2px solid var(--fg-accent);
  border-bottom: 2px solid var(--fg-accent);
  transform: rotate(-45deg);
}
details.fg-details[open] > summary::before { transform: rotate(45deg); }
details.fg-details > summary:hover { background: var(--fg-nav-hover); }
details.fg-details[open] > summary { border-bottom: 1px solid var(--fg-nav-line); }
.fg-details-body { padding: 6px 16px 12px; }

/* ---- tabs: without the script, every part one under another, named */
.fg-tabs { margin: 16px 0; }
.fg-tabbar { display: none; }
html.fg-js .fg-tabbar {
  display: flex; gap: 2px; overflow-x: auto;
  border-bottom: 1px solid var(--fg-nav-line);
}
.fg-tabbar > button {
  appearance: none; background: none; border: 0; font: inherit;
  color: var(--fg-nav-muted); padding: 8px 14px; cursor: pointer;
  font-size: var(--fg-text-size);
  border-bottom: 2px solid transparent; margin-bottom: -1px;
  white-space: nowrap; border-radius: 6px 6px 0 0;
}
.fg-tabbar > button:hover { color: inherit; background: var(--fg-nav-hover); }
.fg-tabbar > button.fg-on {
  color: inherit; font-weight: 600; border-bottom-color: var(--fg-accent);
}
.fg-tabbar > button:focus-visible { outline: 2px solid var(--fg-accent); }
.fg-tab { padding-top: 8px; }
html.fg-js .fg-tab:not(.fg-on) { display: none; }
html:not(.fg-js) .fg-tab::before {
  content: attr(data-title); display: block; font-weight: 700;
  margin: 14px 0 4px;
}
html.fg-js .fg-page:not(.fg-on) { display: none; }

/* ---- the top bar */
.fg-top {
  position: fixed; top: 0; left: 0; right: 0; height: var(--fg-top-h);
  z-index: 60; display: flex; align-items: center; gap: 14px;
  padding: 0 16px; box-sizing: border-box;
  background: var(--fg-nav-bg); color: var(--fg-nav-ink);
  border-bottom: 1px solid var(--fg-nav-line);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif; font-size: 14px;
}
.fg-top-title {
  font-weight: 650; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; max-width: 30vw; color: inherit; text-decoration: none;
}
.fg-top-links { display: flex; gap: 2px; overflow-x: auto; flex: 1; height: 100%; }
.fg-top-links a {
  display: flex; align-items: center; padding: 0 12px; white-space: nowrap;
  color: var(--fg-nav-muted); text-decoration: none;
  border-bottom: 2px solid transparent;
}
.fg-top-links a:hover { color: var(--fg-nav-ink); background: var(--fg-nav-hover); }
.fg-top-links a.fg-on { color: var(--fg-nav-ink); border-bottom-color: var(--fg-accent); font-weight: 600; }
html.fg-has-top body { padding-top: calc(var(--fg-top-h) + 20px) !important; }

/* ---- the sidebar */
.fg-side {
  position: fixed; left: 0; top: var(--fg-top-h); bottom: 0;
  width: var(--fg-side-w); box-sizing: border-box; z-index: 55;
  background: var(--fg-nav-bg); color: var(--fg-nav-ink);
  border-right: 1px solid var(--fg-nav-line);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif; font-size: 13.5px;
  display: flex; flex-direction: column;
  transform: translateX(-100%);
}
html.fg-side-on .fg-side { transform: none; }
.fg-side-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 10px 8px 16px; font-weight: 650; font-size: 12px;
  letter-spacing: 0.06em; text-transform: uppercase; color: var(--fg-nav-muted);
}
.fg-side nav { overflow-y: auto; padding: 0 8px 16px; flex: 1; }
.fg-side ul { list-style: none; margin: 0; padding: 0; }
.fg-side ul ul { padding-left: 12px; margin-left: 9px; border-left: 1px solid var(--fg-nav-line); }
.fg-side li.fg-fold > ul { display: none; }
.fg-side .fg-row { display: flex; align-items: center; }
.fg-side a {
  flex: 1; display: block; padding: 5px 8px; border-radius: 6px;
  color: inherit; text-decoration: none; line-height: 1.3;
}
.fg-side a:hover { background: var(--fg-nav-hover); }
.fg-side a.fg-on { color: var(--fg-accent); background: var(--fg-nav-hover); font-weight: 600; }
.fg-side .fg-twist, .fg-side .fg-row > .fg-gap { width: 18px; flex: none; }
.fg-twist {
  appearance: none; border: 0; background: none; cursor: pointer; height: 22px;
  padding: 0; color: var(--fg-nav-muted); border-radius: 4px;
}
.fg-twist::before {
  content: ""; display: inline-block; width: 5px; height: 5px;
  border-right: 1.5px solid currentColor; border-bottom: 1.5px solid currentColor;
  transform: rotate(45deg); margin-bottom: 2px;
}
/* moving only once the page is up: opening on a shared address must not
   animate into the state it was opened in */
html.fg-ready details.fg-details > summary::before,
html.fg-ready .fg-twist::before { transition: transform 0.15s ease; }
html.fg-ready .fg-side { transition: transform 0.18s ease; }
li.fg-fold > .fg-row > .fg-twist::before { transform: rotate(-45deg); margin-bottom: 0; }
.fg-twist:hover { background: var(--fg-nav-hover); }
.fg-icon-btn {
  appearance: none; border: 1px solid var(--fg-nav-line); background: var(--fg-nav-bg);
  color: var(--fg-nav-ink); border-radius: 7px; width: 30px; height: 30px;
  cursor: pointer; font-size: 15px; line-height: 1; padding: 0; flex: none;
}
.fg-icon-btn:hover { border-color: var(--fg-accent); color: var(--fg-accent); }
.fg-side-open { position: fixed; left: 12px; top: calc(var(--fg-top-h) + 12px); z-index: 50; }
html.fg-has-top .fg-side-open { display: none; }
html.fg-side-on .fg-side-open { display: none; }
@media screen and (min-width: 900px) {
  html.fg-side-on body { margin-left: var(--fg-side-w) !important; }
}
@media screen and (max-width: 899px) {
  html.fg-side-on .fg-side { box-shadow: 0 10px 40px rgba(0, 0, 0, 0.25); }
}
html:not(.fg-js) .fg-side, html:not(.fg-js) .fg-top,
html:not(.fg-js) .fg-side-open { display: none; }

@media print {
  .fg-side, .fg-top, .fg-side-open, .fg-tabbar { display: none !important; }
  html.fg-has-top body { padding-top: 0 !important; }
  html.fg-side-on body { margin-left: 0 !important; }
  .fg-tab, .fg-page { display: block !important; }
  .fg-tab::before {
    content: attr(data-title); display: block; font-weight: 700; margin: 14px 0 4px;
  }
}
"""


LAYOUT_JS = r"""
(function () {
  var cfg = {};
  try { cfg = JSON.parse(document.getElementById("fg-layout-config").textContent); }
  catch (e) { return; }
  var root = document.documentElement, body = document.body;
  root.classList.add("fg-js");
  function all(sel, el) { return Array.prototype.slice.call((el || document).querySelectorAll(sel)); }
  function kids(el, cls) {
    return Array.prototype.filter.call(el.children, function (c) { return c.classList.contains(cls); });
  }
  var applying = false;

  // ------------------------------------------------------------ tabs
  function selectTab(group, name) {
    var panels = kids(group, "fg-tab"), hit = false;
    panels.forEach(function (p) { if (p.getAttribute("data-tab") === name) { hit = true; } });
    if (!hit) { return false; }
    panels.forEach(function (p) { p.classList.toggle("fg-on", p.getAttribute("data-tab") === name); });
    var bar = kids(group, "fg-tabbar")[0];
    if (bar) {
      Array.prototype.forEach.call(bar.children, function (b) {
        var on = b.getAttribute("data-tab") === name;
        b.classList.toggle("fg-on", on);
        b.setAttribute("aria-selected", on ? "true" : "false");
        b.tabIndex = on ? 0 : -1;
      });
    }
    return true;
  }
  all(".fg-tabs").forEach(function (group) {
    var first = kids(group, "fg-tab")[0];
    if (first) { selectTab(group, first.getAttribute("data-tab")); }
    var bar = kids(group, "fg-tabbar")[0];
    if (!bar) { return; }
    bar.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-tab]");
      if (b && selectTab(group, b.getAttribute("data-tab"))) { changed(false); }
    });
    bar.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") { return; }
      var buttons = Array.prototype.slice.call(bar.children);
      var at = buttons.indexOf(document.activeElement);
      if (at < 0) { return; }
      var next = buttons[(at + (e.key === "ArrowRight" ? 1 : buttons.length - 1)) % buttons.length];
      next.focus(); next.click(); e.preventDefault();
    });
  });

  // --------------------------------------------------- folding sections
  all("details.fg-details").forEach(function (d) {
    d.addEventListener("toggle", function () { if (!applying) { changed(false); } });
  });
  var printed = [];
  window.addEventListener("beforeprint", function () {
    printed = all("details:not([open])");
    printed.forEach(function (d) { d.open = true; });
  });
  window.addEventListener("afterprint", function () {
    applying = true;
    printed.forEach(function (d) { d.open = false; });
    printed = []; applying = false;
  });

  // ---------------------------------------- the top level: links or pages
  function isHeading(el) { return /^H[1-6]$/.test(el.tagName); }
  var bodyHeads = Array.prototype.filter.call(body.children, isHeading);
  var level = 0;
  (function () {
    var counts = {};
    bodyHeads.forEach(function (h) { var n = +h.tagName[1]; counts[n] = (counts[n] || 0) + 1; });
    for (var n = 1; n <= 6 && !level; n++) { if (counts[n] >= 2) { level = n; } }
    if (!level && bodyHeads.length) { level = +bodyHeads[0].tagName[1]; }
  })();
  var tops = bodyHeads.filter(function (h) { return +h.tagName[1] === level && h.id; });
  var pages = [];
  if (cfg.navbar === "pages" && tops.length) {
    // each top-level heading and what follows it, up to the next, is a page;
    // what comes before the first is a header on every one
    var current = null;
    Array.prototype.slice.call(body.childNodes).forEach(function (node) {
      if (node.nodeType === 1 && (node.tagName === "SCRIPT" || node.tagName === "STYLE")) {
        current = null; return;
      }
      if (node.nodeType === 1 && tops.indexOf(node) !== -1) {
        current = document.createElement("section");
        current.className = "fg-page";
        current.setAttribute("data-page", node.id);
        body.insertBefore(current, node);
        pages.push(current);
      }
      if (current) { current.appendChild(node); }
    });
  }
  function pageOf(el) { return el.closest ? el.closest(".fg-page") : null; }
  function showPage(page) {
    if (!page) { return; }
    pages.forEach(function (p) { p.classList.toggle("fg-on", p === page); });
    markTop(page.getAttribute("data-page"));
  }

  var top = null, topLinks = {};
  if (cfg.navbar === "links" || cfg.navbar === "pages") {
    root.classList.add("fg-has-top");
    top = document.createElement("header");
    top.className = "fg-top";
    var html = "";
    if (cfg.sidebar !== "off") {
      html += '<button type="button" class="fg-icon-btn fg-menu" title="Contents" aria-label="Contents">☰</button>';
    }
    if (cfg.title) {
      html += '<a class="fg-top-title" href="#"></a>';
    }
    html += '<nav class="fg-top-links" aria-label="Sections"></nav>';
    top.innerHTML = html;
    if (cfg.title) {
      var brand = top.querySelector(".fg-top-title");
      brand.textContent = cfg.title;
      brand.addEventListener("click", function (e) {
        e.preventDefault();
        if (pages.length) { showPage(pages[0]); changed(true); }
        window.scrollTo(0, 0);
      });
    }
    var links = top.querySelector(".fg-top-links");
    tops.forEach(function (h) {
      var a = document.createElement("a");
      a.href = "#" + h.id; a.textContent = h.textContent.trim();
      links.appendChild(a);
      topLinks[h.id] = a;
    });
    body.insertBefore(top, body.firstChild);
  }
  function markTop(id) {
    Object.keys(topLinks).forEach(function (k) { topLinks[k].classList.toggle("fg-on", k === id); });
  }
  if (pages.length) { showPage(pages[0]); }

  // ------------------------------------------------------------ sidebar
  var sideLinks = {};
  var depth = Math.max(1, Math.min(6, cfg.depth || 3));
  if (cfg.sidebar !== "off") {
    var heads = all("h1[id],h2[id],h3[id],h4[id],h5[id],h6[id]").filter(function (h) {
      return !h.closest(".fg-top, .fg-side");
    });
    var base = 7;
    heads.forEach(function (h) { base = Math.min(base, +h.tagName[1]); });
    heads = heads.filter(function (h) { return +h.tagName[1] < base + depth; });
    var side = document.createElement("aside");
    side.className = "fg-side";
    side.setAttribute("aria-label", "Contents");
    side.innerHTML = '<div class="fg-side-head"><span>Contents</span>' +
      '<button type="button" class="fg-icon-btn fg-side-close" title="Hide contents" aria-label="Hide contents">«</button></div><nav><ul></ul></nav>';
    var stack = [{ level: 0, ul: side.querySelector("ul"), li: null }];
    heads.forEach(function (h) {
      var n = +h.tagName[1];
      while (stack.length > 1 && stack[stack.length - 1].level >= n) { stack.pop(); }
      var parent = stack[stack.length - 1];
      if (parent.li && !parent.ul) {
        parent.ul = document.createElement("ul");
        parent.li.appendChild(parent.ul);
        // the top level starts open; deeper branches open as the reader
        // gets to them (setActive), or when their arrow is clicked
        if (parent.level > base) { parent.li.classList.add("fg-fold"); }
        var gap = parent.li.querySelector(".fg-gap");
        var twist = document.createElement("button");
        twist.type = "button"; twist.className = "fg-twist";
        twist.setAttribute("aria-label", "Fold");
        gap.parentNode.replaceChild(twist, gap);
      }
      var li = document.createElement("li");
      li.innerHTML = '<div class="fg-row"><span class="fg-gap"></span><a></a></div>';
      var a = li.querySelector("a");
      a.href = "#" + h.id; a.textContent = h.textContent.trim();
      parent.ul.appendChild(li);
      sideLinks[h.id] = a;
      stack.push({ level: n, ul: null, li: li });
    });
    side.addEventListener("click", function (e) {
      var twist = e.target.closest(".fg-twist");
      if (twist) { twist.closest("li").classList.toggle("fg-fold"); }
    });
    body.appendChild(side);
    var opener = document.createElement("button");
    opener.type = "button";
    opener.className = "fg-icon-btn fg-side-open";
    opener.title = "Show contents"; opener.setAttribute("aria-label", "Show contents");
    opener.textContent = "☰";
    body.appendChild(opener);
    var saved = null;
    try { saved = localStorage.getItem("flograph-sidebar"); } catch (e) {}
    var narrow = window.matchMedia && window.matchMedia("(max-width: 899px)").matches;
    var open = saved ? saved === "open" : cfg.sidebar === "open";
    if (narrow) { open = false; }
    root.classList.toggle("fg-side-on", open);
    function setSide(on) {
      root.classList.toggle("fg-side-on", on);
      try { localStorage.setItem("flograph-sidebar", on ? "open" : "closed"); } catch (e) {}
      window.dispatchEvent(new Event("resize"));
    }
    side.querySelector(".fg-side-close").addEventListener("click", function () { setSide(false); });
    opener.addEventListener("click", function () { setSide(true); });
    var menu = top && top.querySelector(".fg-menu");
    if (menu) {
      menu.addEventListener("click", function () { setSide(!root.classList.contains("fg-side-on")); });
    }
    side.addEventListener("click", function (e) {
      if (e.target.closest("a") && window.matchMedia("(max-width: 899px)").matches) {
        root.classList.remove("fg-side-on");
      }
    });
  }

  // ----------------------------------------------- reveal and go to it
  function reveal(el) {
    var node = el;
    while (node && node !== body) {
      if (node.tagName === "DETAILS" && !node.open) { node.open = true; }
      if (node.classList && node.classList.contains("fg-tab") && node.parentNode) {
        selectTab(node.parentNode, node.getAttribute("data-tab"));
      }
      if (node.classList && node.classList.contains("fg-page")) { showPage(node); }
      node = node.parentNode;
    }
  }
  function goTo(el, push) {
    applying = true;
    reveal(el);
    applying = false;
    el.scrollIntoView();
    setActive(el.id);
    changed(push);
  }
  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) { return; }
    var a = e.target.closest && e.target.closest('a[href^="#"]');
    if (!a) { return; }
    var id = decodeURIComponent(a.getAttribute("href").slice(1));
    if (!id) { return; }
    var el = document.getElementById(id);
    if (!el) { return; }
    e.preventDefault();
    var before = pageOf(el) && !pageOf(el).classList.contains("fg-on");
    goTo(el, !!before);
  });

  // ------------------------------------------------- where the reader is
  var activeId = null;
  function setActive(id) {
    if (id === activeId) { return; }
    activeId = id;
    Object.keys(sideLinks).forEach(function (k) { sideLinks[k].classList.toggle("fg-on", k === id); });
    var a = id && sideLinks[id];
    if (a) {
      var li = a.closest("li");
      while (li) { li.classList.remove("fg-fold"); li = li.parentNode.closest("li"); }
      var nav = a.closest("nav"), r = a.getBoundingClientRect(), n = nav.getBoundingClientRect();
      if (r.top < n.top || r.bottom > n.bottom) { a.scrollIntoView({ block: "nearest" }); }
    }
    if (!pages.length && id) {
      var el = document.getElementById(id), topId = null;
      tops.forEach(function (h) {
        if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING || h === el) { topId = h.id; }
      });
      markTop(topId);
    }
  }
  var spyHeads = all("h1[id],h2[id],h3[id],h4[id],h5[id],h6[id]");
  var ticking = false, atTimer = null;
  function spy() {
    ticking = false;
    var line = parseFloat(getComputedStyle(root).getPropertyValue("--fg-top-h")) || 0;
    line += 24;
    var hit = null;
    for (var i = 0; i < spyHeads.length; i++) {
      var h = spyHeads[i];
      if (!h.offsetParent && h.getClientRects().length === 0) { continue; }
      if (h.getBoundingClientRect().top <= line) { hit = h; } else { break; }
    }
    if (!hit && pages.length) {
      var shown = pages.filter(function (p) { return p.classList.contains("fg-on"); })[0];
      if (shown) { hit = document.getElementById(shown.getAttribute("data-page")); }
    }
    setActive(hit ? hit.id : null);
    clearTimeout(atTimer);
    atTimer = setTimeout(function () { changed(false); }, 400);
  }
  window.addEventListener("scroll", function () {
    if (!ticking) { ticking = true; requestAnimationFrame(spy); }
  }, { passive: true });

  // ------------------------------------------------------- the address
  function stateString() {
    var p = [];
    function put(k, v) { p.push(encodeURIComponent(k) + "=" + encodeURIComponent(v).replace(/%2C/g, ",")); }
    if (pages.length) {
      var shown = pages.filter(function (x) { return x.classList.contains("fg-on"); })[0];
      if (shown && shown !== pages[0]) { put("page", shown.getAttribute("data-page")); }
    }
    all(".fg-tabs[id]").forEach(function (g) {
      var list = kids(g, "fg-tab");
      var on = list.filter(function (t) { return t.classList.contains("fg-on"); })[0];
      if (on && on !== list[0]) { put("tab." + g.id, on.getAttribute("data-tab")); }
    });
    var opened = [], shut = [];
    all("details.fg-details[id]").forEach(function (d) {
      var wasOpen = d.getAttribute("data-fg-default") === "open";
      if (d.open && !wasOpen) { opened.push(d.id); }
      if (!d.open && wasOpen) { shut.push(d.id); }
    });
    if (opened.length) { put("open", opened.join(",")); }
    if (shut.length) { put("shut", shut.join(",")); }
    if (activeId && window.scrollY > 40) { put("at", activeId); }
    return p.join("&");
  }
  function changed(push) {
    if (!cfg.share || applying || !history.replaceState) { return; }
    var state = stateString();
    var url = location.href.split("#")[0] + (state ? "#" + state : "");
    if (url === location.href) { return; }
    try {
      if (push) { history.pushState(null, "", url); } else { history.replaceState(null, "", url); }
    } catch (e) {}
  }
  function apply(hash) {
    hash = (hash || "").replace(/^#/, "");
    if (!hash) {
      if (pages.length) { showPage(pages[0]); }
      return;
    }
    applying = true;
    var target = null;
    try {
      if (hash.indexOf("=") === -1) {
        target = document.getElementById(decodeURIComponent(hash));
      } else {
        var shutting = {};
        hash.split("&").forEach(function (pair) {
          var at = pair.indexOf("=");
          var k = decodeURIComponent(pair.slice(0, at)), v = decodeURIComponent(pair.slice(at + 1));
          if (k === "page") {
            pages.forEach(function (p) { if (p.getAttribute("data-page") === v) { showPage(p); } });
          } else if (k.indexOf("tab.") === 0) {
            var g = document.getElementById(k.slice(4));
            if (g) { selectTab(g, v); }
          } else if (k === "open" || k === "shut") {
            v.split(",").forEach(function (id) {
              var d = document.getElementById(id);
              if (d && d.tagName === "DETAILS") { d.open = k === "open"; }
            });
          } else if (k === "at") {
            target = document.getElementById(v);
          }
        });
      }
      if (target) { reveal(target); }
    } finally { applying = false; }
    if (target) {
      target.scrollIntoView();
      setActive(target.id);
      // pictures above it may still be settling; land on it again once
      // they have
      window.addEventListener("load", function () { target.scrollIntoView(); }, { once: true });
    }
  }
  apply(location.hash);
  requestAnimationFrame(function () {
    requestAnimationFrame(function () { root.classList.add("fg-ready"); });
  });
  window.addEventListener("popstate", function () { apply(location.hash); });
  window.addEventListener("hashchange", function () { apply(location.hash); });
  spy();
})();
"""
