"""Getting round a project's pages (chunk AB): how a `page_ref` param holds
its pages, and which pages a Page Links card shows.

Qt-free, like the rest of core — the Properties panel, the canvas card and
the dashboard tile all read the same answers from here.
"""
from __future__ import annotations

from typing import Iterable, Optional


def split_page_ids(value) -> list[str]:
    """A multi `page_ref`'s stored value as a list of page ids. Stored as a
    comma list because params are JSON scalars; page ids never hold a comma
    (they are uuid hex, or a file's own slugs)."""
    return [part.strip() for part in str(value or "").split(",")
            if part.strip()]


def join_page_ids(ids: Iterable[str]) -> str:
    return ",".join(ids)


# ------------------------------------------------ links in Markdown (AB)

#: The scheme a Markdown link uses to go to a page: [See costs](page:Costs).
PAGE_SCHEME = "page:"


def is_page_link(href) -> bool:
    return str(href or "").strip().lower().startswith(PAGE_SCHEME)


def link_target(href) -> str:
    """What a page link names — `Sales North` for `page:Sales%20North` or
    `<page:Sales North>` — or "" when it is not a page link."""
    from urllib.parse import unquote
    if not is_page_link(href):
        return ""
    return unquote(str(href).strip()[len(PAGE_SCHEME):]).strip("<> \t")


def page_for_link(pages: dict, href) -> Optional[str]:
    """The page a Markdown link like `[Costs](page:Costs)` goes to, or None
    when it is not a page link or names no page.

    By title, ignoring case — the thing someone typing a link knows — or by
    id. A title with spaces goes in as `page:Sales%20North` or in angle
    brackets, `<page:Sales North>`, the two ways Markdown allows. A link by
    title follows the title, so renaming the page breaks it; a Page Links
    card or a Go to page button is the way to a page that survives that.
    """
    target = link_target(href)
    if not target:
        return None
    if target in pages:
        return target
    wanted = target.casefold()
    for page in pages.values():
        if page.title.strip().casefold() == wanted:
            return page.id
    return None


# ------------------------------------------------------- Page Links (AB3)

#: A Page Links card's Show param. Spelled out in the node script too, which
#: is loaded as text and so cannot import them.
SHOW_EVERY = "Every page"
SHOW_GROUP = "This page's group"
SHOW_CHOSEN = "Chosen pages"


#: Page.kind of a tab onto the model canvas itself (G12): the whole canvas
#: (+ ▸ Model canvas), or one frame of it (a frame's Open in New Tab).
CANVAS_KIND = "canvas"


def reader_pages(pages: dict) -> list:
    """The pages someone reading the project can be sent to, in tab order:
    every dashboard and report, and no canvas tab."""
    return [page for page in pages.values() if page.kind != CANVAS_KIND]


def linked_pages(pages: dict, params: dict,
                 host_page_id: Optional[str] = None) -> list:
    """The pages a Page Links card shows, in tab order.

    `pages` is the graph's page dict (already in tab order), `params` the
    card's, and `host_page_id` the page the card sits on — None on the
    canvas, which is no page, so "this page's group" can only mean every
    page there. Chosen pages with nothing chosen is every page as well:
    that is what the picker says it means, and an empty strip is never what
    anyone placed a card of links for. Read at paint time, so a page added
    or renamed is on every card without anyone touching it.

    A canvas tab (G12) is never on one: it is a view of the flow for
    whoever builds it, not a page of the dashboard.
    """
    everything = reader_pages(pages)
    show = params.get("show") or SHOW_EVERY
    if show == SHOW_CHOSEN:
        ids = set(split_page_ids(params.get("pages")))
        return [page for page in everything if page.id in ids] if ids \
            else everything
    if show == SHOW_GROUP and host_page_id in pages:
        group = pages[host_page_id].group
        return [page for page in everything if page.group == group]
    return everything


# ------------------------------------------------------------ tab groups (AB4)

def gather_groups(order: list[str], group_of: dict[str, str]) -> list[str]:
    """`order` with every group's pages brought together, at the place its
    first page already stands. Ungrouped pages keep their places, and so do
    pages within a group, relative to each other.

    The tab bar draws one section per run of a group, so this is what
    keeps a group one section: applied after anything that could split one
    — a drag, a page joining or leaving.
    """
    out: list[str] = []
    placed: set[str] = set()
    for page_id in order:
        if page_id in placed:
            continue
        group = group_of.get(page_id, "")
        if not group:
            out.append(page_id)
            placed.add(page_id)
            continue
        for other in order:
            if other not in placed and group_of.get(other, "") == group:
                out.append(other)
                placed.add(other)
    return out


def order_after_regroup(order: list[str], group_of: dict[str, str],
                        page_id: str, group: str) -> list[str]:
    """The tab order once `page_id` has moved into `group` ("" for none).

    A page joining a group that already has pages goes to the end of that
    group's run. One leaving, or starting a new group, stays where it is —
    and gathering then carries the rest of any group it was in past it, so
    it never ends up splitting its old group in two.
    """
    groups = {**group_of, page_id: group}
    rest = [p for p in order if p != page_id]
    members = [p for p in rest if group and groups.get(p, "") == group]
    at = rest.index(members[-1]) + 1 if members else order.index(page_id)
    rest.insert(at, page_id)
    return gather_groups(rest, groups)


def group_names(order: list[str], group_of: dict[str, str]) -> list[str]:
    """Every group in use, in the order its section appears."""
    names: list[str] = []
    for page_id in order:
        group = group_of.get(page_id, "")
        if group and group not in names:
            names.append(group)
    return names
