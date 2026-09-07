"""A card's size ceiling is written down twice, and the two have to agree.

How big a card may be is stated in `ui/canvas/node_item.py` (the drag
handle's bounds, per card kind) and again in the node's own `PARAMS` (the
Width / Height spinboxes in the properties panel). Nothing connected them,
so raising one alone moved nothing: drag past the node's own max and the
spinbox clamps it back; type past the item's max and the drag bounds clamp
it back. That is not a thing anyone can debug from the outside — the card
simply refuses to grow and no message says which of the two said no.

A node script is Qt-free by contract and cannot import a UI constant, so
the duplication is not removable. This is the guard rail instead.
"""
import pytest

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas.node_item import NodeItem

#: Params that state a *card's* size. A node may also have width/height
#: params meaning something else entirely (a figure's own layout size), so
#: the card ones are identified the way the properties panel identifies
#: them: cosmetic, and named width or height.
SIZE_PARAMS = ("width", "height")


def card_size_params(spec):
    """`{name: ParamSpec}` for the cosmetic width/height a card resizes."""
    return {p.name: p for p in spec.params
            if p.name in SIZE_PARAMS and p.cosmetic}


def resizable_cards(registry, graph):
    """Every builtin whose card can actually be dragged bigger, as
    (type_id, NodeItem, {param name: ParamSpec})."""
    out = []
    for spec in registry.all():
        params = card_size_params(spec)
        if not params:
            continue
        item = NodeItem(graph.add_node(registry.instantiate(spec.type_id)))
        if not item._resizable():
            continue
        out.append((spec.type_id, item, params))
    return out


@pytest.fixture(scope="module")
def cards(qapp):
    registry = NodeRegistry()
    registry.load_builtins()
    return resizable_cards(registry, Graph())


class TestTheTwoCeilingsAgree:
    def test_there_are_cards_to_check(self, cards):
        """Guard against the sweep silently matching nothing."""
        assert len(cards) > 15

    def test_every_card_agrees_on_its_widest(self, cards):
        wrong = []
        for type_id, item, params in cards:
            _minw, maxw, _minh, _maxh = item._resize_bounds()
            spec_max = params["width"].maximum if "width" in params else None
            if spec_max is not None and float(spec_max) != float(maxw):
                wrong.append(f"{type_id}: PARAMS says {spec_max:g}, "
                             f"the card says {maxw:g}")
        assert not wrong, "width ceilings disagree —\n  " + "\n  ".join(wrong)

    def test_every_card_agrees_on_its_tallest(self, cards):
        wrong = []
        for type_id, item, params in cards:
            _minw, _maxw, _minh, maxh = item._resize_bounds()
            spec_max = params["height"].maximum if "height" in params else None
            if spec_max is not None and float(spec_max) != float(maxh):
                wrong.append(f"{type_id}: PARAMS says {spec_max:g}, "
                             f"the card says {maxh:g}")
        assert not wrong, "height ceilings disagree —\n  " + "\n  ".join(wrong)

    def test_no_card_advertises_a_floor_it_will_refuse(self, cards):
        """The same trap at the other end, but not the same rule.

        A ceiling has to match exactly — one of the two always lies about
        how big a card may be. A floor does not: the card's is generic to
        its *kind* ("any control is at least 120 wide") and a node may
        reasonably be stricter, since a date picker needs more room than a
        toggle. What is never right is a node advertising a floor *below*
        the card's, because typing that number gets it silently clamped.

        A minimum of 0 is exempt: on the Note it is the documented
        "0 = fit text" sentinel, not a size at all.
        """
        wrong = []
        for type_id, item, params in cards:
            minw, _maxw, minh, _maxh = item._resize_bounds()
            for name, floor in (("width", minw), ("height", minh)):
                spec = params.get(name)
                if spec is None or not spec.minimum:
                    continue
                if float(spec.minimum) < float(floor):
                    wrong.append(f"{type_id}.{name}: PARAMS offers "
                                 f"{spec.minimum:g}, the card refuses under "
                                 f"{floor:g}")
        assert not wrong, "floors below the card's —\n  " + "\n  ".join(wrong)
