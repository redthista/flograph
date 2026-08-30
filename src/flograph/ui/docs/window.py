"""The documentation window — Help ▸ Documentation, or F1.

Modeless, like the Statistics window and the feature help dialogs it sits
beside: it is read *while* working on a flow, so it must not block the canvas
behind it. A thin shell around `WikiView` pointed at the bundled handbook.
"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout

from ..wiki import WikiView


class DocsWindow(QDialog):
    """Modeless, reused across openings — one window, raised again rather than
    restacked, like the Statistics window it sits beside."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("flograph — Documentation")
        self.setModal(False)
        self.resize(960, 720)

        self.view = WikiView(self, folder=None, show_nav=True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.view)

    def show_page(self, slug: str) -> None:
        """Open the window on a particular page — for a future 'help on this'
        entry point."""
        self.view.show_page(slug)
