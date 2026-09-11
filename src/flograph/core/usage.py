"""Where a node is shown — the answer a project only keeps one way round.

A dashboard tile stores the id of the node it renders; a report page names
one by label. Both links point *from* the page *to* the node, because that
is the direction the app needs in order to draw anything. Nothing keeps the
reverse. So the question people actually ask of a board that has grown —
"is this chart still used anywhere, and where?" — has no answer short of
opening every page and reading it.

This module is that answer, derived the way `core.links` derives Goto/From
links: a pure function over the graph, computed when asked and stored
nowhere. There is no index to keep in step with edits, and nothing to go
stale. Nothing here imports Qt, so the lookup is testable without a window
and the menu and the Navigator share one implementation rather than growing
two that quietly disagree.

Three places count as a use, because all three put the node in front of
somebody:

- a **dashboard tile**, which names the node by id, so the match is exact
  and a page may hold the same node twice — two tiles, two answers;
- a **report page**, whose ``![[label]]`` names it by label. A label is not
  unique, and where two nodes answer to one the page itself refuses to
  guess (see `ui.report.render.by_label`). This reports that rather than
  hiding it: a use you share with another node is still a use, but it is
  not proof the page means *you*;
- a **report card** on the canvas, which is a page that happens to live in
  the model. Leaving it out would let "used by no page" be said about a
  node somebody is looking at. A card's embed names one of its own *inputs*
  first, so that half of the lookup follows the wire, not the label.

"Used by no page" is a first-class answer here, not an empty result the
caller has to interpret — on a board that has grown it is the question
people are really asking.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from .report import find_embeds, nodes_labelled

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .graph import Graph

#: A tile on a dashboard page.
DASHBOARD = "dashboard"
#: An ``![[embed]]`` in a report page's body.
REPORT = "report"
#: An ``![[embed]]`` in a Report *card* sitting on the model canvas.
CARD = "card"

#: The card kind whose `text` param is a report body. One name, so adding a
#: second bodied card kind later is one edit rather than a hunt.
REPORT_CARD = "report"
#: The param that body lives in (`nodes/viz/report_card.py`).
BODY_PARAM = "text"


@dataclass(frozen=True)
class Use:
    """One place a node is shown.

    Carries what it takes to *go* there as well as what it takes to say it,
    because an answer to "where is this used?" that cannot take you there
    is a riddle.
    """
    kind: str                       # DASHBOARD | REPORT | CARD
    title: str                      # the page's title, or the card's label
    page_id: Optional[str] = None   # None for a card: it lives on the model
    tile_id: Optional[str] = None   # dashboard only
    host_id: Optional[str] = None   # the report card's node id
    port: Optional[str] = None      # the output shown, where one was named
    #: character offset of the first embed in the body, for scrolling to it;
    #: -1 on a dashboard, where the tile is the thing you navigate to
    at: int = -1
    #: how many embeds on that page name this node — a page is one answer
    #: however often it says it, but "three times" is worth knowing
    times: int = 1
    #: other nodes answering to the same label. Non-zero means the page
    #: cannot tell which of you it meant, and shows a warning where the
    #: embed is.
    shared_with: int = 0

    @property
    def is_shared(self) -> bool:
        return self.shared_with > 0


def all_uses(graph: "Graph") -> dict[str, list[Use]]:
    """Every use in the project, by node id, in the order somebody meets
    them: pages in tab order, then report cards in model order.

    One pass over the pages rather than one pass per node, so the Navigator
    can mark a whole canvas without walking every page again for each item.
    """
    found: dict[str, list[Use]] = {}

    def add(node_id: str, use: Use) -> None:
        found.setdefault(node_id, []).append(use)

    for page in graph.pages.values():
        if page.kind == REPORT:
            for node_id, use in _embed_uses(graph, page.body, REPORT,
                                            title=page.title,
                                            page_id=page.id):
                add(node_id, use)
        else:
            for tile in page.tiles.values():
                if tile.node_id:
                    add(tile.node_id,
                        Use(DASHBOARD, page.title, page_id=page.id,
                            tile_id=tile.id, port=tile.port))

    for host in report_cards(graph):
        body = str(host.params.get(BODY_PARAM, "") or "")
        for node_id, use in _embed_uses(graph, body, CARD, title=host.label,
                                        host_id=host.id):
            add(node_id, use)

    return found


def uses_of(graph: "Graph", node_id: str) -> list[Use]:
    """Every place `node_id` is shown. Empty means used by no page."""
    if node_id not in graph.nodes:
        return []
    return all_uses(graph).get(node_id, [])


def report_cards(graph: "Graph") -> list:
    """The nodes whose params hold a report body."""
    return [n for n in graph.nodes.values()
            if getattr(n.spec, "card", None) == REPORT_CARD]


def _embed_uses(graph, body, kind, *, title, page_id=None, host_id=None):
    """`(node_id, Use)` for every node the embeds in `body` name.

    A body is one answer per node however many times it names it, so the
    embeds are collapsed as they are found and the *first* one keeps the
    offset — that is the one to scroll to.
    """
    host = graph.nodes.get(host_id) if host_id else None
    inputs = {p.name for p in host.spec.inputs} if host is not None else set()

    collapsed: dict[str, dict] = {}
    for embed in find_embeds(body):
        # A card's embed names one of its own inputs first, and the port
        # segment wins that check — the same order as
        # `ui.report.render.by_wired_input`, so this agrees with what the
        # card actually renders even for `![[anything|table]]`.
        name = (embed.port or embed.ref).strip()
        if name in inputs:
            conn = graph.input_connection(host_id, name)
            if conn is None:
                continue            # nothing wired: the card says so itself
            matches, shared = [conn.src_node], 0
            port = conn.src_port
        else:
            found = nodes_labelled(graph, embed.ref)
            matches = [n.id for n in found]
            shared = len(found) - 1
            port = embed.port or None

        for node_id in matches:
            seen = collapsed.get(node_id)
            if seen is None:
                collapsed[node_id] = {"at": embed.start, "times": 1,
                                      "port": port, "shared": shared}
            else:
                seen["times"] += 1
                # the worst case is the one worth reporting: if any embed on
                # the page is ambiguous, the page is ambiguous about you
                seen["shared"] = max(seen["shared"], shared)

    return [(node_id,
             Use(kind, title, page_id=page_id, host_id=host_id,
                 port=info["port"], at=info["at"], times=info["times"],
                 shared_with=info["shared"]))
            for node_id, info in collapsed.items()]


# --------------------------------------------------------------- wording
#
# The menu, the Navigator and the status bar all have to say the same thing
# about the same use, so they say it from here.

#: What each kind of place is called, in the singular, for a sentence.
_PLACE = {DASHBOARD: "Dashboard page",
          REPORT: "Report page",
          CARD: "Report card"}

#: "Used by no page" — the answer worth having a name for.
NOWHERE = "Used by no page"


def _times(count: int) -> str:
    if count <= 1:
        return ""
    return " (twice)" if count == 2 else f" ({count} times)"


def describe(use: Use) -> str:
    """One line naming the place, the way a menu says it."""
    line = f"{_PLACE.get(use.kind, 'Page')} “{use.title}”{_times(use.times)}"
    if use.is_shared:
        others = use.shared_with
        line += (f" — shared with {others} other node"
                 f"{'s' if others > 1 else ''} of this name")
    return line


def summarise(uses: list[Use]) -> str:
    """The whole answer in one sentence, for a status bar or a tooltip."""
    if not uses:
        return NOWHERE
    if len(uses) == 1:
        return f"Used on {describe(uses[0])}"
    places = ", ".join(describe(use) for use in uses)
    return f"Used in {len(uses)} places: {places}"
