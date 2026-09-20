"""The spell check as the editors meet it: the setting, the highlighter
that draws the squiggle, and the menu that offers the corrections.

The words and every rule about them are in `flograph.core.spelling`, which
is Qt-free. This is the thin Qt layer over it, shared by the three places a
flow holds prose — a report page's source, a Report card and a Note — so
all three behave the same and there is one place to change it.

**Only while it is being written.** A squiggle belongs on an editor and
nowhere else: a locked page, a rendered preview, a printed PDF and the
exported HTML never build a highlighter, so "not on the final output" is
not a rule anything has to remember — it falls out of where this lives.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import (QAction, QColor, QSyntaxHighlighter,
                           QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                               QPlainTextEdit, QVBoxLayout)

from flograph.core.spelling import (DEFAULT_LANGUAGE, LANGUAGES, Checker,
                                    my_words, opens_or_closes_a_fence,
                                    set_my_words)
from flograph.core.spelling import learn_word as _learn

_ORG = "flograph"
_APP = "flograph"

ENABLED_SETTING = "spelling/enabled"
LANGUAGE_SETTING = "spelling/language"

#: How many corrections a right-click offers before it stops.
MAX_SUGGESTIONS = 7

#: The squiggle's colour. Qt draws a SpellCheckUnderline in the platform's
#: own style; the colour is ours, chosen to read on the editor's dark
#: ground without competing with an error marker.
UNDERLINE = QColor("#e06c75")


class _SpellNotifier(QObject):
    """One signal every open editor listens to, so turning the check off
    or changing the dictionary clears what is already on screen instead of
    only what is opened next."""
    changed = Signal()


_notifier = _SpellNotifier()


def spell_check_changed() -> Signal:
    return _notifier.changed


def spell_check_enabled() -> bool:
    """On unless it has been turned off. It costs nothing until something
    is typed and it only ever appears in an editor, so a writing aid that
    has to be found and switched on is a writing aid nobody has."""
    return bool(QSettings(_ORG, _APP).value(ENABLED_SETTING, True, type=bool))


def set_spell_check_enabled(on: bool) -> None:
    QSettings(_ORG, _APP).setValue(ENABLED_SETTING, bool(on))
    _notifier.changed.emit()


def spell_language() -> str:
    value = str(QSettings(_ORG, _APP).value(LANGUAGE_SETTING,
                                            DEFAULT_LANGUAGE) or "")
    return value if value in LANGUAGES else DEFAULT_LANGUAGE


def set_spell_language(language: str) -> None:
    QSettings(_ORG, _APP).setValue(
        LANGUAGE_SETTING,
        language if language in LANGUAGES else DEFAULT_LANGUAGE)
    _notifier.changed.emit()


def learn_word(word: str) -> None:
    """Teach the user's own dictionary a word, and redraw every editor
    that is open — a word accepted in one has to be accepted in all."""
    _learn(word)
    _notifier.changed.emit()


def set_learned_words(words) -> None:
    """Replace the user's own dictionary, from the Settings editor."""
    set_my_words(words)
    _notifier.changed.emit()


class SpellHighlighter(QSyntaxHighlighter):
    """Underlines the words in a document that are not words.

    `extra` is a callable, and defaults to the user's own dictionary: it
    can grow from the menu below while this is attached, so asking each
    time is what keeps a just-learned word from staying underlined.

    A fenced code block is skipped whole, which is the one thing a
    line-at-a-time highlighter needs state for — Qt's own block state
    carries it.
    """

    IN_FENCE = 1

    def __init__(self, document, extra: Optional[Callable[[], Iterable[str]]]
                 = None) -> None:
        super().__init__(document)
        self._extra = my_words if extra is None else extra
        self._checker = Checker(spell_language())
        self._format = QTextCharFormat()
        self._format.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
        self._format.setUnderlineColor(UNDERLINE)
        _notifier.changed.connect(self.refresh)

    @property
    def checker(self) -> Checker:
        self._checker.set_language(spell_language())
        self._checker.set_extra(self._extra())
        return self._checker

    def refresh(self) -> None:
        """Re-read the setting and redraw. Safe after the document has
        gone: Qt disconnects a deleted receiver itself, and a highlighter
        whose document is closing simply has nothing to do."""
        try:
            self.rehighlight()
        except RuntimeError:            # the document went first
            pass

    def highlightBlock(self, text: str) -> None:
        was_fenced = self.previousBlockState() == self.IN_FENCE
        fenced = was_fenced
        if opens_or_closes_a_fence(text):
            fenced = not was_fenced
        self.setCurrentBlockState(self.IN_FENCE if fenced else 0)
        # the line that opens or closes a fence is punctuation, and every
        # line inside one is code
        if was_fenced or fenced or not spell_check_enabled():
            return
        for start, end, _word in self.checker.unknown(text):
            self.setFormat(start, end - start, self._format)


class SpellingMenu(QObject):
    """Puts the corrections on an editor's *standard* context menu.

    An event filter rather than a subclass because the editors that want
    this are already built — a report page's source box is a plain
    QPlainTextEdit with a completer and a highlighter hung off it, and
    swapping its class to add one menu section would be the tail wagging
    the dog. An editor with a menu of its own (a Report card's Insert
    entries) calls `add_spelling_actions` directly instead.
    """

    def __init__(self, editor, highlighter: "SpellHighlighter",
                 on_learn: Optional[Callable[[str], None]] = None) -> None:
        super().__init__(editor)
        self._editor = editor
        self._highlighter = highlighter
        self._on_learn = on_learn
        # A text editor is a scroll area, and a right-click lands on its
        # *viewport* — a filter on the editor itself sees the menu key and
        # nothing a mouse does, which is the whole of the gesture. Both are
        # watched: the keyboard's menu key does arrive at the editor.
        editor.installEventFilter(self)
        editor.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent

        if event.type() != QEvent.ContextMenu:
            return False
        if obj is not self._editor and obj is not self._editor.viewport():
            return False
        # the word is found by viewport position, so an event that came to
        # the editor is moved onto the viewport before it is read
        point = event.pos()
        if obj is self._editor:
            point = self._editor.viewport().mapFrom(self._editor, point)
        menu = self.menu_for(point)
        self._show(menu, event.globalPos())
        menu.deleteLater()
        return True

    def menu_for(self, point):
        """The editor's standard menu with the corrections for the word at
        `point` (in viewport coordinates) above it. Separate from opening
        it so a test can read the menu without one appearing on screen."""
        menu = self._editor.createStandardContextMenu()
        add_spelling_actions(menu, self._editor, self._highlighter.checker,
                             self._on_learn, point)
        return menu

    def _show(self, menu, at) -> None:
        menu.exec(at)


def word_under(editor, position=None) -> tuple:
    """The prose word at a point in an editor, as (word, start, end) in
    document positions — or ("", 0, 0) where there is no word to correct.

    `position` is a point in the editor's viewport (a right-click); with
    none it is wherever the caret is.
    """
    cursor = (editor.cursorForPosition(position) if position is not None
              else editor.textCursor())
    block = cursor.block()
    offset = cursor.position() - block.position()
    for start, end, word in _spans(block.text()):
        # the word the point is in, or the one it sits at the end of, so
        # right-clicking just past a typo still offers it
        if start <= offset <= end:
            return word, block.position() + start, block.position() + end
    return "", 0, 0


def _spans(text: str):
    from flograph.core.spelling import prose_spans
    return prose_spans(text)


def add_spelling_actions(menu, editor, checker: Checker,
                         on_learn: Optional[Callable[[str], None]] = None,
                         position=None) -> bool:
    """Put the corrections for the word under `position` at the top of a
    context menu. True when it added anything.

    `on_learn` is how a word is remembered — a column name, a product,
    somebody's surname. Without one the "add" entry is left off rather
    than offered and ignored.
    """
    if not spell_check_enabled():
        return False
    word, start, end = word_under(editor, position)
    if not word or checker.knows(word):
        return False

    first = menu.actions()[0] if menu.actions() else None

    def replace(with_word: str) -> None:
        cursor = editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        cursor.insertText(with_word)
        editor.setTextCursor(cursor)

    suggestions = checker.suggest(word, MAX_SUGGESTIONS)
    if suggestions:
        for suggestion in suggestions:
            action = QAction(suggestion, menu)
            action.triggered.connect(
                lambda _checked=False, s=suggestion: replace(s))
            menu.insertAction(first, action)
    else:
        nothing = QAction("No suggestions", menu)
        nothing.setEnabled(False)
        menu.insertAction(first, nothing)

    if on_learn is not None:
        learn = QAction(f"Add “{word}” to my dictionary", menu)
        learn.triggered.connect(lambda _checked=False, w=word: on_learn(w))
        menu.insertAction(first, learn)
    menu.insertSeparator(first)
    return True


class MyDictionaryDialog(QDialog):
    """The words you have taught it, as a list you can edit.

    A plain text box rather than a table with buttons: the list is a list
    of words, pasting fifty column names into it is the thing people will
    actually want, and the file behind it has the same shape — so what is
    edited here and what is edited in a text editor cannot disagree.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("My dictionary")
        self.resize(360, 420)
        from flograph.core.spelling import dictionary_path

        self._box = QPlainTextEdit("\n".join(my_words()))
        self._box.setObjectName("my_dictionary_words")
        self._box.setPlaceholderText("One word per line")
        where = QLabel(f"One word per line. Saved in {dictionary_path()}")
        where.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self._box, 1)
        layout.addWidget(where)
        layout.addWidget(buttons)

    def words(self) -> list:
        return self._box.toPlainText().splitlines()

    def accept(self) -> None:
        set_learned_words(self.words())
        super().accept()
