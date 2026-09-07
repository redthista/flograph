"""Copying code out of the editor keeps its indentation.

Pasting a node's script into an email arrived with every indent gone
unless "paste as unformatted" was used — which is not something anyone
should have to know. A QPlainTextEdit offers the clipboard only
`text/plain`; the mail client converts that to HTML itself, and HTML
collapses runs of spaces. The editor now offers a `<pre>` flavour of its
own, which is the only way to say "this whitespace matters".
"""
import pytest
from PySide6.QtGui import QTextCursor

from flograph.ui.editor.code_editor import CodeEditor

SCRIPT = """def run(ctx, table):
    if table is None:
        raise ValueError("no table")
    return {"table": table}
"""


@pytest.fixture
def editor(qapp):
    widget = CodeEditor()
    widget.setPlainText(SCRIPT)
    return widget


def copied(widget):
    """The mime data a Ctrl+C of the whole document would put on the
    clipboard — taken through the editor's own selection, not built."""
    widget.selectAll()
    return widget.createMimeDataFromSelection()


class TestCopyingCode:
    def test_the_plain_text_is_the_script_unchanged(self, editor):
        """The flavour a terminal or another editor takes must not move."""
        assert copied(editor).text().rstrip("\n") == SCRIPT.rstrip("\n")

    def test_there_is_an_html_flavour_too(self, editor):
        assert copied(editor).hasHtml()

    def test_the_indentation_survives_into_the_html(self, editor):
        html = copied(editor).html()
        assert "    if table is None:" in html
        assert "        raise ValueError" in html

    def test_the_html_says_the_whitespace_matters(self, editor):
        """Without <pre> (or an equivalent white-space rule) the receiving
        application is entitled to collapse the indentation, which is the
        whole bug."""
        html = copied(editor).html()
        assert "<pre" in html and "white-space:pre" in html

    def test_the_lines_are_still_lines(self, editor):
        """selectedText() separates blocks with U+2029, not a newline.
        Passed through as-is the whole script pastes as one line."""
        html = copied(editor).html()
        assert "\u2029" not in html
        assert html.count("\n") >= SCRIPT.strip().count("\n")

    def test_code_cannot_smuggle_markup_into_the_paste(self, editor):
        """A script is text, and a `<` in it is a less-than sign."""
        editor.setPlainText("if a < b and c > d:\n    x = '<b>'\n")
        html = copied(editor).html()
        assert "&lt;" in html and "&gt;" in html
        assert "<b>" not in html

    def test_an_empty_selection_offers_no_html(self, editor):
        """Nothing selected is nothing copied — don't put an empty <pre>
        on the clipboard for a stray Ctrl+C."""
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.Start)
        editor.setTextCursor(cursor)
        assert not editor.createMimeDataFromSelection().hasHtml()

    def test_one_indented_line_on_its_own_keeps_its_indent(self, editor):
        """The case that actually gets pasted into an email: a fragment,
        not the whole file."""
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.Start)
        cursor.movePosition(QTextCursor.Down)
        cursor.movePosition(QTextCursor.EndOfLine, QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        html = editor.createMimeDataFromSelection().html()
        assert "    if table is None:" in html
