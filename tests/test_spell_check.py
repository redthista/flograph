"""Spell check on the three places a flow holds prose — a report page's
source, a Report card and a Note (0.1.15 #17).

Two halves, and the seam between them is the point: `flograph.core.spelling`
is Qt-free and holds every rule about what a word is, what prose is and
what a correction is; `flograph.ui.editor.spell_check` is the thin layer
that draws a squiggle and builds a menu. A rule tested here is tested once.
"""
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QTextCharFormat, QUndoStack
from PySide6.QtWidgets import QMenu, QPlainTextEdit

from flograph.core import Graph, NodeRegistry, Page
from flograph.core.spelling import (DEFAULT_LANGUAGE, LANGUAGES, Checker,
                                    opens_or_closes_a_fence, prose_spans)
from flograph.ui.canvas import NodeGraphScene


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture(scope="module")
def uk():
    return Checker("en_GB")


def words(checker, line):
    return [w for _s, _e, w in checker.unknown(line)]


class TestTheDictionaryIsBundled:
    """No dependency to install and nothing to fetch: it has to work on a
    machine that allows neither, and inside the one-file build."""

    def test_both_languages_load(self):
        for language in LANGUAGES:
            assert len(Checker(language).dictionary.words) > 50000

    def test_british_is_the_default(self):
        assert DEFAULT_LANGUAGE == "en_GB"

    def test_an_unknown_language_falls_back_rather_than_failing(self):
        assert Checker("klingon").language == DEFAULT_LANGUAGE

    def test_the_licence_travels_with_the_words(self):
        """The lists are redistributable on the condition that the notice
        goes with them, so the notice is inside each file."""
        import gzip
        import importlib.resources

        for name in ("core", "en_GB", "en_US"):
            blob = (importlib.resources.files("flograph.spelling")
                    / f"{name}.txt.gz").read_bytes()
            head = gzip.decompress(blob).decode("utf-8")[:1200]
            assert "Kevin Atkinson" in head and "SCOWL" in head


class TestWhatCountsAsSpelled:
    def test_an_ordinary_word(self, uk):
        assert uk.knows("dictionary") and not uk.knows("dictionarie")

    def test_the_two_englishes_disagree_where_they_should(self):
        gb, us = Checker("en_GB"), Checker("en_US")
        assert gb.knows("colour") and gb.knows("organise")
        assert not gb.knows("favorite") and not gb.knows("organize")
        assert us.knows("favorite") and us.knows("organize")
        assert not us.knows("colour") and not us.knows("organise")

    def test_and_agree_on_everything_else(self):
        gb, us = Checker("en_GB"), Checker("en_US")
        for word in ("revenue", "quarter", "dashboard", "table"):
            assert gb.knows(word) and us.knows(word)

    def test_a_name_needs_its_capital(self, uk):
        assert uk.knows("London") and uk.knows("LONDON")
        assert not uk.knows("london")

    def test_an_ordinary_word_does_not_have_to_lose_one(self, uk):
        assert uk.knows("the") and uk.knows("The") and uk.knows("THE")

    def test_a_possessive_is_the_word_it_is_made_from(self, uk):
        assert uk.knows("London's") and uk.knows("London’s")
        assert not uk.knows("Lundon's")

    def test_something_too_short_is_never_marked(self, uk):
        """Two letters is mostly initials and maths, and a squiggle under
        "x" teaches nobody anything."""
        assert uk.knows("xq") and uk.knows("zz")

    def test_the_projects_own_words_count(self, uk):
        checker = Checker("en_GB", ["Flograph", "Widgetron"])
        assert checker.knows("flograph") and checker.knows("Widgetron")
        assert not uk.knows("Widgetron")


class TestOnlyProseIsChecked:
    """A report page is markdown with machinery in it. Underlining an
    embed, a URL or a variable would make the whole feature an irritation
    rather than a help."""

    @pytest.mark.parametrize("line", [
        "See ![[Revenue by Quarterr]] below.",
        "A [[Wiki Linkk]] here.",
        "Run `df.describ()` on it.",
        "The rate is ${discountt}.",
        "Read https://example.com/mispeled for more.",
        "Mail zzqq@exampl.com about it.",
        "Open data/raww/input.csv first.",
        "A [link](httpp://zzqq.example) in text.",
        "An <spann> tag.",
        "A &nbspx; entity.",
    ])
    def test_the_machine_readable_parts_are_left_alone(self, uk, line):
        assert words(uk, line) == []

    def test_but_the_prose_around_them_is_not(self, uk):
        assert words(uk, "See ![[Revenue]] for teh details.") == ["teh"]

    def test_a_word_with_a_digit_in_it_is_not_a_word(self, uk):
        assert words(uk, "Column col_2 and q1sales are fine.") == []

    def test_a_fence_is_a_fence(self):
        assert opens_or_closes_a_fence("```python")
        assert opens_or_closes_a_fence("~~~")
        assert not opens_or_closes_a_fence("a ``` mid-line")

    def test_a_span_says_where_the_word_is(self, uk):
        line = "the teh word"
        assert uk.unknown(line) == [(4, 7, "teh")]
        assert [s[2] for s in prose_spans(line)] == ["the", "teh", "word"]


class TestSuggestions:
    @pytest.mark.parametrize("typo,wanted", [
        ("teh", "the"), ("recieve", "receive"), ("seperate", "separate"),
        ("definately", "definitely"), ("accomodate", "accommodate"),
        ("yuo", "you"), ("adn", "and"),
    ])
    def test_the_obvious_correction_comes_first(self, uk, typo, wanted):
        assert uk.suggest(typo)[0] == wanted

    def test_a_suggestion_is_dressed_the_way_the_word_was_typed(self, uk):
        assert uk.suggest("Teh")[0] == "The"
        assert uk.suggest("TEH")[0] == "THE"

    def test_a_word_nothing_is_near_gets_nothing(self, uk):
        assert uk.suggest("qwertyuiopzxcv") == []

    def test_the_projects_own_words_are_offered_too(self):
        checker = Checker("en_GB", ["Widgetron"])
        assert "Widgetron" in checker.suggest("Widgetro")

    def test_it_never_suggests_the_word_itself(self, uk):
        assert "colour" not in uk.suggest("colour")


@pytest.fixture
def my_dictionary(tmp_path, monkeypatch):
    """A word list of this test's own, beside a throwaway profile."""
    from flograph.core import spelling

    monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path))
    spelling.forget_words()
    yield tmp_path / "dictionary.txt"
    spelling.forget_words()


class TestMyOwnWords:
    """Column names, product names, surnames. A spell check with nowhere
    to put them is a wall of red that gets turned off on the first
    afternoon — and they belong to the person, not to one project, so the
    same jargon follows them from flow to flow."""

    def test_a_learned_word_lands_beside_the_other_settings(self,
                                                            my_dictionary):
        from flograph.core.spelling import dictionary_path, learn_word

        assert dictionary_path() == my_dictionary
        learn_word("Widgetron")
        assert "Widgetron" in my_dictionary.read_text()

    def test_it_is_a_plain_list_a_person_can_edit(self, my_dictionary):
        from flograph.core.spelling import forget_words, learn_word, my_words

        learn_word("Widgetron")
        my_dictionary.write_text(my_dictionary.read_text() + "Acme\n")
        forget_words()
        assert my_words() == ["Widgetron", "Acme"]

    def test_it_dedupes_without_case_keeping_what_was_written(self,
                                                              my_dictionary):
        from flograph.core.spelling import my_words, set_my_words

        set_my_words(["Acme", "acme", " ", "# a comment", "Widgetron"])
        assert my_words() == ["Acme", "Widgetron"]

    def test_no_file_is_no_words_rather_than_an_error(self, my_dictionary):
        from flograph.core.spelling import my_words

        assert not my_dictionary.exists()
        assert my_words() == []

    def test_the_checker_takes_them(self, my_dictionary):
        from flograph.core.spelling import learn_word, my_words

        learn_word("Widgetron")
        assert Checker("en_GB", my_words()).knows("widgetron")

    def test_a_project_file_carries_none_of_this(self, registry):
        """It moved out of the project on purpose — a .flograph emailed to
        somebody should not be teaching their spell check words."""
        from flograph.core.serialization import graph_to_dict

        assert "spelling_words" not in graph_to_dict(Graph())["graph"]


def marked(editor):
    """The words a highlighter underlined, in document order."""
    from flograph.ui.editor.spell_check import UNDERLINE

    out = []
    block = editor.document().firstBlock()
    while block.isValid():
        text = block.text()
        for run in block.layout().formats():
            if run.format.underlineColor() == UNDERLINE:
                out.append(text[run.start:run.start + run.length])
        block = block.next()
    return out


@pytest.fixture
def clean_settings(qtbot, monkeypatch):
    """The setting is per user; a test must not depend on, or leave, one."""
    from flograph.ui.editor import spell_check

    store = {}
    monkeypatch.setattr(spell_check, "spell_check_enabled",
                        lambda: store.get("on", True))
    monkeypatch.setattr(spell_check, "spell_language",
                        lambda: store.get("language", "en_GB"))
    return store


class TestTheSquiggle:
    def _editor(self, qtbot, text):
        from flograph.ui.editor.spell_check import SpellHighlighter

        editor = QPlainTextEdit()
        qtbot.addWidget(editor)
        speller = SpellHighlighter(editor.document())
        editor.setPlainText(text)
        return editor, speller

    def test_it_underlines_what_is_not_a_word(self, qtbot, clean_settings):
        editor, _ = self._editor(qtbot, "The quick brown fox jumpd over.")
        assert marked(editor) == ["jumpd"]

    def test_it_leaves_a_fenced_code_block_alone(self, qtbot, clean_settings):
        editor, _ = self._editor(
            qtbot, "A sentance here.\n```\nzzz qqq notaword\n```\nAnd sentance.")
        assert marked(editor) == ["sentance", "sentance"]

    def test_turning_it_off_clears_what_is_on_screen(self, qtbot,
                                                     clean_settings):
        editor, speller = self._editor(qtbot, "A sentance.")
        assert marked(editor) == ["sentance"]
        clean_settings["on"] = False
        speller.refresh()
        assert marked(editor) == []

    def test_changing_the_dictionary_redraws(self, qtbot, clean_settings):
        editor, speller = self._editor(qtbot, "The colour of the organiser.")
        assert marked(editor) == []
        clean_settings["language"] = "en_US"
        speller.refresh()
        assert marked(editor) == ["colour", "organiser"]

    def test_a_learned_word_stops_being_marked(self, qtbot, clean_settings):
        from flograph.ui.editor.spell_check import SpellHighlighter

        learned = []
        editor = QPlainTextEdit()
        qtbot.addWidget(editor)
        speller = SpellHighlighter(editor.document(), lambda: learned)
        editor.setPlainText("Widgetron sells widgets.")
        assert marked(editor) == ["Widgetron"]
        learned.append("Widgetron")
        speller.refresh()
        assert marked(editor) == []


class TestOnACard:
    """A Note and a Report card share one editor, so they share this."""

    @pytest.fixture
    def env(self, qtbot, registry):
        graph = Graph()
        stack = QUndoStack()
        scene = NodeGraphScene(graph, stack, registry=registry)
        note = graph.add_node(registry.instantiate("flograph.util.note"))
        graph.set_param(note.id, "text", "A sentance about Widgetron.")
        return graph, stack, scene.node_items[note.id]

    def test_typing_in_a_note_is_checked(self, qtbot, clean_settings,
                                         my_dictionary, env):
        _graph, _stack, item = env
        item.start_note_edit()
        assert marked(item._note_editor_widget) == ["sentance", "Widgetron"]

    def test_the_menu_offers_corrections(self, qtbot, clean_settings, env):
        from flograph.ui.editor.spell_check import add_spelling_actions

        _graph, _stack, item = env
        item.start_note_edit()
        editor = item._note_editor_widget
        cursor = editor.textCursor()
        cursor.setPosition(4)              # inside "sentance"
        editor.setTextCursor(cursor)
        menu = QMenu()
        qtbot.addWidget(menu)
        assert add_spelling_actions(menu, editor, editor._speller.checker)
        assert "sentence" in [a.text() for a in menu.actions()]

    def test_picking_one_replaces_the_word(self, qtbot, clean_settings, env):
        from flograph.ui.editor.spell_check import add_spelling_actions

        _graph, _stack, item = env
        item.start_note_edit()
        editor = item._note_editor_widget
        cursor = editor.textCursor()
        cursor.setPosition(4)
        editor.setTextCursor(cursor)
        menu = QMenu()
        qtbot.addWidget(menu)
        add_spelling_actions(menu, editor, editor._speller.checker)
        next(a for a in menu.actions() if a.text() == "sentence").trigger()
        assert editor.toPlainText() == "A sentence about Widgetron."

    def test_adding_a_word_writes_it_and_clears_the_mark(
            self, qtbot, clean_settings, my_dictionary, env):
        from flograph.core.spelling import my_words
        from flograph.ui.editor.spell_check import add_spelling_actions

        _graph, _stack, item = env
        item.start_note_edit()
        editor = item._note_editor_widget
        assert marked(editor) == ["sentance", "Widgetron"]
        cursor = editor.textCursor()
        cursor.setPosition(20)             # inside "Widgetron"
        editor.setTextCursor(cursor)
        menu = QMenu()
        qtbot.addWidget(menu)
        add_spelling_actions(menu, editor, editor._speller.checker,
                             editor._learn)
        learn = next(a for a in menu.actions() if a.text().startswith("Add"))
        learn.trigger()
        assert my_words() == ["Widgetron"]
        assert marked(editor) == ["sentance"]

    def test_a_word_it_knows_gets_no_menu(self, qtbot, clean_settings, env):
        from flograph.ui.editor.spell_check import add_spelling_actions

        _graph, _stack, item = env
        item.start_note_edit()
        editor = item._note_editor_widget
        cursor = editor.textCursor()
        cursor.setPosition(1)              # inside "A"… the first word
        editor.setTextCursor(cursor)
        menu = QMenu()
        qtbot.addWidget(menu)
        assert not add_spelling_actions(menu, editor,
                                        editor._speller.checker)
        assert menu.actions() == []


class TestOnAReportPage:
    """The source box is checked; nothing a reader sees ever is."""

    @pytest.fixture
    def page(self, qtbot, registry):
        from flograph.engine import ExecutionEngine
        from flograph.ui.report import ReportPage

        graph = Graph()
        graph.add_page(Page(id="p1", title="Q3", kind="report"))
        widget = ReportPage(graph, ExecutionEngine(graph), QUndoStack(), "p1")
        qtbot.addWidget(widget)
        yield widget, graph
        widget.dispose()

    def test_the_source_box_is_checked(self, qtbot, clean_settings, page):
        widget, _graph = page
        widget.editor.setPlainText("A sentance in the report.")
        assert marked(widget.editor) == ["sentance"]

    def test_an_embed_is_not_marked(self, qtbot, clean_settings, page):
        widget, _graph = page
        widget.editor.setPlainText("Totals: ![[Totall|height=3]] and teh rest.")
        assert marked(widget.editor) == ["teh"]

    def test_the_css_box_is_left_alone(self, qtbot, clean_settings, page):
        """CSS is not prose. `nowrap` and `rgba` are not typos."""
        widget, _graph = page
        widget.css_editor.setPlainText("body { white-space: nowrap; }")
        assert marked(widget.css_editor) == []

    def test_locking_the_page_takes_the_editor_away_with_its_marks(
            self, qtbot, clean_settings, page):
        """The other half of "only while editing": view mode hides the
        source box, so there is nowhere for a squiggle to be."""
        widget, _graph = page
        widget.editor.setPlainText("A sentance in the report.")
        widget.set_view_mode(True)
        assert not widget.editor.isVisibleTo(widget)

    def test_what_a_reader_sees_carries_no_marks(self, qtbot, clean_settings,
                                                 page):
        """The preview, the PDF and the HTML are built from the *text*, so
        a squiggle cannot reach any of them — asserted on the HTML, which
        is the one a reader could receive as a file."""
        from flograph.ui.report.html import report_html
        from flograph.ui.report.render import render_report

        widget, graph = page
        widget.editor.setPlainText("A sentance in the report.")
        html = report_html(render_report("A sentance in the report.", graph,
                                         widget._engine.cache))
        assert "sentance" in html
        assert "underline" not in html.lower()


class TestRightClickingOnAReportPage:
    """The source box is a scroll area, so a right-click lands on its
    *viewport*. A filter watching the editor itself sees the menu key and
    nothing a mouse does — which is the whole of the gesture, and is why
    the page offered the plain undo/cut/copy/paste menu and no
    corrections.
    """

    @pytest.fixture
    def page(self, qtbot, registry, clean_settings, my_dictionary,
             monkeypatch):
        from flograph.engine import ExecutionEngine
        from flograph.ui.editor.spell_check import SpellingMenu
        from flograph.ui.report import ReportPage

        # caught rather than opened: a modal menu in a test never closes
        self.opened = []
        monkeypatch.setattr(SpellingMenu, "_show",
                            lambda _self, menu, _at: self.opened.append(menu))
        graph = Graph()
        graph.add_page(Page(id="p1", title="Q3", kind="report"))
        widget = ReportPage(graph, ExecutionEngine(graph), QUndoStack(), "p1")
        qtbot.addWidget(widget)
        widget.editor.setPlainText("A sentance in the report.")
        yield widget
        widget.dispose()

    def _right_click(self, widget, target, at=4):
        """Right-click inside the word starting at `at`."""
        from PySide6.QtGui import QContextMenuEvent
        from PySide6.QtWidgets import QApplication

        cursor = widget.editor.textCursor()
        cursor.setPosition(at)
        point = widget.editor.cursorRect(cursor).center()
        event = QContextMenuEvent(
            QContextMenuEvent.Mouse, point,
            widget.editor.viewport().mapToGlobal(point))
        return QApplication.sendEvent(target, event)

    def test_the_menu_a_mouse_asks_for_carries_the_corrections(self, page):
        assert self._right_click(page, page.editor.viewport())
        assert self.opened, "the viewport's context menu was not ours"
        assert "sentence" in [a.text() for a in self.opened[0].actions()]

    def test_and_so_does_the_one_the_menu_key_asks_for(self, page):
        assert self._right_click(page, page.editor)
        assert self.opened
        assert "sentence" in [a.text() for a in self.opened[0].actions()]

    def test_it_still_offers_the_ordinary_entries(self, page):
        """The corrections go *above* cut/copy/paste, not instead of."""
        self._right_click(page, page.editor.viewport())
        labels = [a.text().replace("&", "") for a in self.opened[0].actions()]
        assert any(label.startswith("Paste") for label in labels)

    def test_a_word_it_knows_gets_the_plain_menu(self, page):
        self._right_click(page, page.editor.viewport(), at=15)  # "the"
        labels = [a.text() for a in self.opened[0].actions()]
        assert not any(label.startswith("Add") for label in labels)

    def test_adding_a_word_from_the_page_teaches_the_user(self, page):
        from flograph.core.spelling import my_words

        page.editor.setPlainText("Widgetron sells widgets.")
        assert marked(page.editor) == ["Widgetron"]
        self._right_click(page, page.editor.viewport(), at=3)
        learn = next(a for a in self.opened[0].actions()
                     if a.text().startswith("Add"))
        assert "my dictionary" in learn.text()
        learn.trigger()
        assert my_words() == ["Widgetron"]
        assert marked(page.editor) == []
