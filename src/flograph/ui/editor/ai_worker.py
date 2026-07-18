"""Runs flograph.ai.suggest_node_update() off the Qt thread.

A synchronous HTTP call to a local LLM can take several seconds; doing it
on the UI thread would freeze the app. Mirrors the JediWorker/
CompletionController pattern in completion.py: a QObject worker moved to a
dedicated QThread, owned by a controller parented to the editor.

The controller — not the editor panel — must own the shutdown-on-destroyed
connection: Qt skips delivering a destroyed() signal to a slot whose
receiver is itself mid-destruction, and the editor panel is exactly that
object when its own deleteChildren() is what's tearing the editor down. A
controller parented to (and destroyed as a child of) the editor is still a
live receiver at that moment, so its shutdown slot actually runs.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

from flograph import ai


class AiAssistantWorker(QObject):
    succeeded = Signal(int, str)   # request_id, updated source
    failed = Signal(int, str)      # request_id, error message

    @Slot(int, str, str, str, object)
    def suggest(self, request_id: int, source: str, instruction: str,
                type_id: str, config: Optional[ai.LLMConfig]) -> None:
        try:
            code = ai.suggest_node_update(source, instruction, type_id, config)
        except (ai.LLMError, ValueError) as exc:
            self.failed.emit(request_id, str(exc))
            return
        except Exception as exc:  # unexpected — still surface, don't crash the app
            self.failed.emit(request_id, f"AI assistant failed: {exc}")
            return
        self.succeeded.emit(request_id, code)


class AiAssistantController(QObject):
    """Owns the worker thread; parent it to the CodeEditor it serves."""

    succeeded = Signal(int, str)   # request_id, updated source
    failed = Signal(int, str)      # request_id, error message
    _request_suggestion = Signal(int, str, str, str, object)

    def __init__(self, editor: QObject) -> None:
        super().__init__(editor)
        self._thread = QThread(self)
        self._worker = AiAssistantWorker()
        self._worker.moveToThread(self._thread)
        self._request_suggestion.connect(self._worker.suggest)
        self._worker.succeeded.connect(self.succeeded)
        self._worker.failed.connect(self.failed)
        self._thread.start()

        editor.destroyed.connect(self.shutdown)

    def request_suggestion(self, request_id: int, source: str,
                            instruction: str, type_id: str,
                            config: Optional[ai.LLMConfig] = None) -> None:
        self._request_suggestion.emit(
            request_id, source, instruction, type_id, config)

    def shutdown(self) -> None:
        if self._thread.isRunning():
            self._thread.quit()
            # no timeout: quit() is queued behind any in-flight request, and
            # abandoning a running QThread aborts the process
            self._thread.wait()
