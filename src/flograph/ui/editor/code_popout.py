"""A node's code in a window of its own.

The Code panel shares a narrow right-hand column with Properties and Log, and
a script of any length in it means scrolling both ways. The ⤢ in its header
opens the same code in a window that can be made as big as the work needs.
It is the Properties pop-out (properties/text_popout) with Python in place of
a box's words: the panel's highlighting and jedi completion, find and
replace, several carets, and a syntax check as you type.

The check as you type is compile() and nothing more. The node's own check
(parse_spec) runs the script's top-level code, imports and all, which is too
much for every keystroke; it runs once, on OK. A script it refuses keeps the
window open with the reason under the editor, so the work isn't lost to a
typo the way it would be if the window closed first.
"""
from __future__ import annotations

import re

from flograph.core import NodeScriptError, parse_spec
from flograph.core.text_assist import Diagnostic, TextAssist

from ..properties.text_popout import ERROR_INK, TextPopOut
from .code_editor import CodeEditor
from .completion import CompletionController

_SYNTAX_LINE = re.compile(r"syntax error on line (\d+)")


def python_syntax_lint(text: str, _sample=None) -> list:
    """Where Python would refuse to compile the text, as a Diagnostic.
    compile() stops at the first error, so there is at most one."""
    try:
        compile(text, "<code>", "exec")
    except SyntaxError as exc:
        return [Diagnostic(exc.lineno or 1, exc.msg or "invalid syntax")]
    except ValueError as exc:  # a null byte pasted in
        return [Diagnostic(1, str(exc))]
    return []


class CodePopOut(TextPopOut):
    """`editor` holds the copy being edited; read it back after exec()."""

    UNCHECKED = ""  # there are no columns to check in a script

    def __init__(self, title: str, text: str, *, type_id: str,
                 read_only: bool = False, parent=None) -> None:
        super().__init__(title, text,
                         assist=TextAssist(lint=python_syntax_lint),
                         read_only=read_only, parent=parent)
        self._type_id = type_id
        self.setObjectName("code_popout")
        self.editor.setObjectName("code_popout_editor")
        self.resize(960, 700)

    def _assist_editor(self, editor: CodeEditor, columns: list) -> None:
        # CodeEditor comes with the Python highlighter already
        self.completer = CompletionController(editor)

    def accept(self) -> None:
        """OK: only a script the node would take. The same check Apply
        makes, so a refused script stays here to be fixed."""
        if not self.editor.isReadOnly():
            try:
                parse_spec(self.editor.toPlainText(), self._type_id)
            except NodeScriptError as exc:
                match = _SYNTAX_LINE.search(str(exc))
                self.editor.set_error_line(
                    int(match.group(1)) if match else None)
                self._say(f"Not applied — {exc}", ERROR_INK)
                return
        super().accept()
