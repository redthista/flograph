""""Where is this visual used?" — the reverse of the link a page keeps.

Qt-free, because `core.usage` is: a page names the node it shows, and this
is that lookup run backwards over the whole project.
"""
import pytest

from flograph.core import Graph, NodeRegistry, Page, Tile
from flograph.core.usage import (
    CARD, DASHBOARD, NOWHERE, REPORT, all_uses, describe, summarise, uses_of,
)

CONST = "flograph.util.constant"
REPORT_CARD = "flograph.viz.report_card"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def graph():
    return Graph()


def node(graph, registry, label, type_id=CONST):
    made = graph.add_node(registry.instantiate(type_id))
    graph.set_label(made.id, label)
    return made


class TestATileOnADashboard:

    def test_the_page_that_shows_it_is_the_answer(self, graph, registry):
        chart = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Today"))
        graph.add_tile("p1", Tile(id="t1", node_id=chart.id, port="value"))

        (use,) = uses_of(graph, chart.id)
        assert use.kind == DASHBOARD
        assert use.title == "Today"
        assert (use.page_id, use.tile_id, use.port) == ("p1", "t1", "value")

    def test_a_node_on_no_page_says_so(self, graph, registry):
        lonely = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Today"))
        assert uses_of(graph, lonely.id) == []
        assert summarise(uses_of(graph, lonely.id)) == NOWHERE

    def test_the_same_node_twice_on_one_page_is_two_answers(self, graph,
                                                            registry):
        """Two tiles are two things you can be taken to, so collapsing them
        would lose the half of the answer that navigates."""
        chart = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Today"))
        graph.add_tile("p1", Tile(id="t1", node_id=chart.id))
        graph.add_tile("p1", Tile(id="t2", node_id=chart.id))

        assert [u.tile_id for u in uses_of(graph, chart.id)] == ["t1", "t2"]

    def test_pages_come_back_in_tab_order(self, graph, registry):
        chart = node(graph, registry, "Revenue")
        for page_id, title in (("p1", "First"), ("p2", "Second")):
            graph.add_page(Page(id=page_id, title=title))
            graph.add_tile(page_id, Tile(id=f"t_{page_id}", node_id=chart.id))

        assert [u.title for u in uses_of(graph, chart.id)] == ["First",
                                                               "Second"]

    def test_a_tile_left_pointing_at_a_deleted_node_answers_nothing(
            self, graph, registry):
        graph.add_page(Page(id="p1", title="Today"))
        graph.add_tile("p1", Tile(id="t1", node_id="gone"))
        assert uses_of(graph, "gone") == []


class TestAnEmbedOnAReportPage:

    def test_the_label_finds_the_node(self, graph, registry):
        chart = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Monthly", kind="report",
                            body="# Sales\n\n![[Revenue]]\n"))

        (use,) = uses_of(graph, chart.id)
        assert use.kind == REPORT
        assert use.title == "Monthly"
        assert use.page_id == "p1"

    def test_the_offset_is_where_the_first_one_starts(self, graph, registry):
        chart = node(graph, registry, "Revenue")
        body = "# Sales\n\n![[Revenue]]\n"
        graph.add_page(Page(id="p1", title="Monthly", kind="report",
                            body=body))

        (use,) = uses_of(graph, chart.id)
        assert body[use.at:use.at + 13] == "![[Revenue]]\n"[:13]

    def test_naming_it_three_times_is_one_page_and_a_count(self, graph,
                                                           registry):
        chart = node(graph, registry, "Revenue")
        graph.add_page(Page(
            id="p1", title="Monthly", kind="report",
            body="![[Revenue]]\n\n![[Revenue|value]]\n\n![[Revenue]]\n"))

        (use,) = uses_of(graph, chart.id)
        assert use.times == 3

    def test_a_label_written_inside_code_is_an_example_not_a_use(
            self, graph, registry):
        """`find_embeds` already knows this; the point is that the reverse
        lookup goes through it rather than round it."""
        chart = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="How to", kind="report",
                            body="Write `![[Revenue]]` to embed it.\n"))

        assert uses_of(graph, chart.id) == []

    def test_the_match_ignores_case_the_way_the_page_does(self, graph,
                                                          registry):
        chart = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Monthly", kind="report",
                            body="![[ revenue ]]\n"))

        assert len(uses_of(graph, chart.id)) == 1


class TestWhenTwoNodesAnswerToOneLabel:
    """The page refuses to guess which it meant. So does this — but it says
    the use is shared rather than dropping it, because the node may well be
    the one on the page and the reader is the one who can tell."""

    def test_both_nodes_are_told_about_the_page(self, graph, registry):
        first = node(graph, registry, "Revenue")
        second = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Monthly", kind="report",
                            body="![[Revenue]]\n"))

        for made in (first, second):
            (use,) = uses_of(graph, made.id)
            assert use.shared_with == 1
            assert use.is_shared

    def test_and_the_wording_says_why_it_is_uncertain(self, graph, registry):
        first = node(graph, registry, "Revenue")
        node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Monthly", kind="report",
                            body="![[Revenue]]\n"))

        assert "shared with 1 other node" in describe(uses_of(graph,
                                                              first.id)[0])

    def test_an_unshared_label_says_nothing_about_sharing(self, graph,
                                                          registry):
        chart = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Monthly", kind="report",
                            body="![[Revenue]]\n"))

        assert uses_of(graph, chart.id)[0].shared_with == 0
        assert "shared" not in describe(uses_of(graph, chart.id)[0])


class TestAReportCardIsAPageThatLivesOnTheCanvas:
    """Leaving these out would let "used by no page" be said about a node
    somebody is looking at."""

    def test_an_embed_that_names_a_wired_input_follows_the_wire(
            self, graph, registry):
        source = node(graph, registry, "Feeder")
        card = node(graph, registry, "Summary", REPORT_CARD)
        graph.connect(source.id, "value", card.id, "a")
        graph.set_param(card.id, "text", "Total was ![[a]].")

        (use,) = uses_of(graph, source.id)
        assert use.kind == CARD
        assert use.title == "Summary"
        assert use.host_id == card.id
        assert use.page_id is None      # it is on the model, not a page

    def test_an_input_name_wins_over_a_node_of_that_label(self, graph,
                                                           registry):
        """`by_wired_input`'s rule: unplugging a wire must not silently swap
        the source of a paragraph, so an input name always resolves as one."""
        wired = node(graph, registry, "Feeder")
        decoy = node(graph, registry, "a")
        card = node(graph, registry, "Summary", REPORT_CARD)
        graph.connect(wired.id, "value", card.id, "a")
        graph.set_param(card.id, "text", "![[a]]")

        assert [u.host_id for u in uses_of(graph, wired.id)] == [card.id]
        assert uses_of(graph, decoy.id) == []

    def test_the_port_segment_wins_that_check_too(self, graph, registry):
        """`![[anything|a]]` names the input `a` — the same order the card
        renders by."""
        wired = node(graph, registry, "Feeder")
        card = node(graph, registry, "Summary", REPORT_CARD)
        graph.connect(wired.id, "value", card.id, "a")
        graph.set_param(card.id, "text", "![[whatever|a]]")

        assert [u.host_id for u in uses_of(graph, wired.id)] == [card.id]

    def test_an_unwired_input_is_nobody_s_use(self, graph, registry):
        card = node(graph, registry, "Summary", REPORT_CARD)
        graph.set_param(card.id, "text", "![[a]]")
        assert all_uses(graph) == {}

    def test_a_name_that_is_no_input_falls_back_to_the_label(self, graph,
                                                             registry):
        chart = node(graph, registry, "Revenue")
        card = node(graph, registry, "Summary", REPORT_CARD)
        graph.set_param(card.id, "text", "![[Revenue]]")

        assert [u.host_id for u in uses_of(graph, chart.id)] == [card.id]

    def test_cards_come_after_pages(self, graph, registry):
        chart = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Monthly", kind="report",
                            body="![[Revenue]]"))
        card = node(graph, registry, "Summary", REPORT_CARD)
        graph.set_param(card.id, "text", "![[Revenue]]")

        assert [u.kind for u in uses_of(graph, chart.id)] == [REPORT, CARD]


class TestOnePassForTheWholeProject:

    def test_all_uses_answers_for_every_node_at_once(self, graph, registry):
        chart = node(graph, registry, "Revenue")
        table = node(graph, registry, "Detail")
        node(graph, registry, "Scratch")
        graph.add_page(Page(id="p1", title="Today"))
        graph.add_tile("p1", Tile(id="t1", node_id=chart.id))
        graph.add_page(Page(id="p2", title="Monthly", kind="report",
                            body="![[Revenue]]\n\n![[Detail]]"))

        found = all_uses(graph)
        assert set(found) == {chart.id, table.id}
        assert len(found[chart.id]) == 2

    def test_a_node_that_is_gone_has_no_uses(self, graph):
        assert uses_of(graph, "never-existed") == []


class TestSayingIt:

    def test_a_dashboard_reads_as_a_page(self, graph, registry):
        chart = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Today"))
        graph.add_tile("p1", Tile(id="t1", node_id=chart.id))

        assert describe(uses_of(graph, chart.id)[0]) == \
            "Dashboard page “Today”"

    def test_twice_is_worded_as_twice(self, graph, registry):
        chart = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Monthly", kind="report",
                            body="![[Revenue]] ![[Revenue]]"))

        assert describe(uses_of(graph, chart.id)[0]) == \
            "Report page “Monthly” (twice)"

    def test_more_than_twice_is_counted(self, graph, registry):
        chart = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Monthly", kind="report",
                            body="![[Revenue]] " * 4))

        assert "(4 times)" in describe(uses_of(graph, chart.id)[0])

    def test_nothing_has_its_own_sentence(self):
        assert summarise([]) == NOWHERE

    def test_several_places_are_counted_and_named(self, graph, registry):
        chart = node(graph, registry, "Revenue")
        graph.add_page(Page(id="p1", title="Today"))
        graph.add_tile("p1", Tile(id="t1", node_id=chart.id))
        graph.add_page(Page(id="p2", title="Monthly", kind="report",
                            body="![[Revenue]]"))

        line = summarise(uses_of(graph, chart.id))
        assert line.startswith("Used in 2 places:")
        assert "Dashboard page “Today”" in line
        assert "Report page “Monthly”" in line
