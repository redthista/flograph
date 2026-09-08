"""The full value where a cell was cut short (V3, the free half).

A read-only table fits its columns to their content and then clamps the
width, so a long value is elided — and there was no way to find out what it
said. Copying the cell worked, which is a strange thing to have to do to
read a table.

The awkward part is *where* the answer lives. Qt only offers the tooltip
the **model** supplies, and a model cannot know how wide its column ended
up. The **view** knows the width but not what the decorations took, and the
**delegate** is the only thing that knows how much of the cell was left for
the value. So the view asks the delegate, and the tooltip is offered only
when the text genuinely did not fit — a tooltip on a cell you can already
read in full is noise, and noise is what stops people reading the ones that
matter.

The other half is a **note from another column** (`revenue tooltip note`)
— a comment that explains a number without spending a column of the table
to say it. That one is a rule, so it comes from the model; the cut-short
text cannot, because it depends on how wide the column ended up. A cell
can have both, and there is one tooltip, so both are shown: the note
first, because it is the thing somebody deliberately wrote.
"""
import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QStyleOptionViewItem

pd = pytest.importorskip("pandas")

from flograph.core.table_format import parse_rules              # noqa: E402
from flograph.ui.data_table import DataTableView                # noqa: E402
from flograph.ui.inspector.pandas_model import PandasModel      # noqa: E402

LONG = "a description far too long to fit in any sensible column"

FRAME = pd.DataFrame({
    "note": [LONG, "ok"],
    "region": ["South", "North"],
})


def view_for(frame=FRAME, rules_text="", width=90, **kw):
    view = DataTableView()
    view.setModel(PandasModel(frame, rules=parse_rules(rules_text), **kw))
    view.resize(400, 200)
    view.setColumnWidth(0, width)
    return view


def value_width(view, row=0, column=0) -> int:
    """The room the delegate left for the value in one cell."""
    index = view.model().index(row, column)
    option = QStyleOptionViewItem()
    view.initViewItemOption(option)
    option.rect = view.visualRect(index)
    area = view.itemDelegate().value_area(option, index)
    return -1 if area is None else area.width()


class TestOnlyWhenSomethingWasCut:
    def test_a_value_that_did_not_fit_offers_the_whole_of_itself(self, qapp):
        view = view_for()
        assert view._tooltip_text(view.model().index(0, 0)) == LONG

    def test_a_value_that_fits_says_nothing(self, qapp):
        view = view_for()
        assert view._tooltip_text(view.model().index(1, 0)) == ""

    def test_widening_the_column_takes_the_tooltip_away(self, qapp):
        view = view_for(width=2000)
        assert view._tooltip_text(view.model().index(0, 0)) == ""

    def test_an_empty_cell_has_nothing_to_add(self, qapp):
        frame = pd.DataFrame({"note": [None]})
        view = view_for(frame)
        assert view._tooltip_text(view.model().index(0, 0)) == ""

    def test_a_wrapping_table_is_left_alone(self, qapp):
        """`wrap` exists precisely so that nothing is cut off. Measuring a
        wrapped cell on one line would fire on text that is perfectly
        readable, several lines further down."""
        view = view_for(rules_text="wrap")
        assert view._tooltip_text(view.model().index(0, 0)) == ""


class TestWhatTheDecorationsTook:
    """The reason this measurement belongs to the delegate and not to a
    fontMetrics call in the view."""

    def test_a_mark_beside_the_value_leaves_it_less_room(self, qapp):
        plain = value_width(view_for())
        marked = value_width(view_for(
            rules_text="note if region = South => icon ✓ green"))
        assert 0 < marked < plain

    def test_a_lozenge_costs_its_own_padding(self, qapp):
        plain = value_width(view_for())
        pilled = value_width(view_for(
            rules_text="note if region = South => pill red"))
        assert 0 < pilled < plain

    def test_a_decoration_standing_in_for_the_value_offers_nothing(self, qapp):
        """The value is not shortened there — it is deliberately not shown,
        which is what `only` and `in` were asked for."""
        view = view_for(rules_text="note if region = South => icon ✓ green in")
        assert value_width(view) == -1
        assert view._tooltip_text(view.model().index(0, 0)) == ""


class TestItDoesNotTalkOverAnyoneElse:
    def test_a_tooltip_the_model_supplies_comes_first(self, qapp):
        """A model that has something to say knows why it is talking, so it
        leads — but on a cut cell the value still has to be reachable, or
        the papercut comes back on exactly the cells someone annotated."""
        from PySide6.QtGui import QStandardItem, QStandardItemModel
        model = QStandardItemModel(1, 1)
        item = QStandardItem(LONG)
        item.setToolTip("the model's own words")
        model.setItem(0, 0, item)
        view = DataTableView()
        view.setModel(model)
        view.resize(400, 200)
        view.setColumnWidth(0, 90)
        text = view._tooltip_text(model.index(0, 0))
        assert text.startswith("the model's own words")
        assert LONG in text

    def test_the_header_still_explains_its_column(self, qapp):
        """The dtype tooltip on a header predates this and is a different
        question — the two must not have become one."""
        model = PandasModel(FRAME)
        assert "dtype" in model.headerData(0, Qt.Horizontal, Qt.ToolTipRole)


class TestANoteFromAnotherColumn:
    """`revenue tooltip note` — a comment that explains a number without
    spending a column of the table to say it."""

    def test_the_note_shows_on_a_cell_that_fits_perfectly_well(self, qapp):
        view = view_for(rules_text="region tooltip note", width=200)
        assert view._tooltip_text(view.model().index(1, 1)) == "ok"

    def test_a_blank_note_says_nothing(self, qapp):
        """An empty note is no note, not an empty tooltip hovering over
        the cell."""
        frame = pd.DataFrame({"region": ["South", "North"],
                              "note": ["", "why this one is late"]})
        view = view_for(frame, "region tooltip note", width=200)
        assert view._tooltip_text(view.model().index(0, 0)) == ""
        assert view._tooltip_text(view.model().index(1, 0)) == (
            "why this one is late")

    def test_a_cell_with_both_shows_the_note_then_the_value(self, qapp):
        """There is one tooltip and two things want it. Showing either
        alone loses the other."""
        frame = pd.DataFrame({"note": [LONG], "why": ["second shift"]})
        view = view_for(frame, "note tooltip why", width=90)
        text = view._tooltip_text(view.model().index(0, 0))
        assert text.startswith("second shift")
        assert LONG in text
        assert text.index("second shift") < text.index(LONG)

    def test_the_note_survives_a_wrapping_table(self, qapp):
        """`wrap` suppresses the cut-short half, which is measured. It must
        not suppress a rule somebody wrote."""
        view = view_for(rules_text="region tooltip note\nwrap", width=200)
        assert view._tooltip_text(view.model().index(1, 1)) == "ok"

    def test_the_note_column_keeps_showing_unless_hidden(self, qapp):
        """Deliberate: `hide` says it out loud, and a rule that silently
        drops a column is a kindness people then have to undo."""
        view = view_for(rules_text="region tooltip note")
        heads = [view.model().headerData(i, Qt.Horizontal, Qt.DisplayRole)
                 for i in range(view.model().columnCount())]
        assert "note" in heads

    def test_a_note_column_the_table_lacks_paints_nothing(self, qapp):
        view = view_for(rules_text="region tooltip nosuchcolumn", width=200)
        assert view._tooltip_text(view.model().index(1, 1)) == ""

    def test_it_prints_as_a_title_attribute(self):
        """Paper has no hover, but Open in Browser does — and the exported
        HTML is the same document."""
        from flograph.core.table_html import frame_to_html
        html = frame_to_html(FRAME, parse_rules("region tooltip note"))
        assert 'title="ok"' in html


class TestTheEventItself:
    def test_a_tooltip_event_is_answered_here(self, qapp):
        view = view_for()
        event = QHelpEvent(QEvent.ToolTip, QPoint(5, 5), QPoint(5, 5))
        assert view.viewportEvent(event) is True

    def test_an_event_over_no_cell_at_all_is_harmless(self, qapp):
        view = view_for()
        far = QPoint(10_000, 10_000)
        assert view.viewportEvent(QHelpEvent(QEvent.ToolTip, far, far)) is True

    def test_a_view_with_no_model_does_not_fall_over(self, qapp):
        view = DataTableView()
        event = QHelpEvent(QEvent.ToolTip, QPoint(5, 5), QPoint(5, 5))
        assert view.viewportEvent(event) is True
