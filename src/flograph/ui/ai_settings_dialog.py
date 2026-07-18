"""AI Assistant settings dialog (Tools > AI Assistant Settings…).

Persists the local-LLM connection (base URL, model, optional API key) via
QSettings, under the same "flograph"/"flograph" org/app used everywhere
else in the UI. load_llm_config() is the read side other UI code calls
before firing an "Ask AI" request.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLineEdit, QMessageBox, QPushButton,
)

from flograph import ai

_ORG = "flograph"
_APP = "flograph"

_INFO_TEXT = """\
When you click "Ask AI" on a node, three things are sent to the Base URL \
configured here — nothing passes through any flograph-run server first:

1. A fixed instruction describing flograph's node contract (no data — the \
same every time).
2. The current node's source code — the NODE / PARAMS / run() text shown \
in the code editor.
3. The instruction you type (e.g. "format the date column as YYYY-MM-DD").

What is NOT sent:

• The actual data flowing through the node (dataframe or column values) — \
run() is never executed as part of this, so there's no data to send.
• Parameter values set via the Properties panel (file paths, connection \
strings, etc.) — those aren't part of the script text.
• Any other node's code, or the rest of the graph.

One caveat: if a literal value (e.g. a file path or key) is hardcoded \
directly in the node's script instead of set via the Properties panel, it \
will be included — it's part of the source code sent to the server."""


def load_llm_config() -> ai.LLMConfig:
    settings = QSettings(_ORG, _APP)
    return ai.LLMConfig(
        base_url=settings.value("ai/base_url", ai.DEFAULT_BASE_URL, type=str),
        model=settings.value("ai/model", ai.DEFAULT_MODEL, type=str),
        api_key=settings.value("ai/api_key", "", type=str) or None,
    )


class AiSettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI Assistant Settings")
        self.resize(480, 160)

        config = load_llm_config()

        self._base_url = QLineEdit(config.base_url)
        self._base_url.setPlaceholderText(ai.DEFAULT_BASE_URL)

        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.setInsertPolicy(QComboBox.NoInsert)
        self._model.addItem(config.model)
        self._model.setCurrentText(config.model)
        self._fetch_models_btn = QPushButton("Fetch Models")
        self._fetch_models_btn.setToolTip(
            "Query the server's /models endpoint, using the Base URL and "
            "API key above")
        self._fetch_models_btn.clicked.connect(self._fetch_models)
        model_row = QHBoxLayout()
        model_row.addWidget(self._model, 1)
        model_row.addWidget(self._fetch_models_btn)

        self._api_key = QLineEdit(config.api_key or "")
        self._api_key.setPlaceholderText("(optional — most local servers don't need one)")
        self._api_key.setEchoMode(QLineEdit.Password)

        form = QFormLayout(self)
        form.addRow("Base URL", self._base_url)
        form.addRow("Model", model_row)
        form.addRow("API key", self._api_key)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self._info_btn = buttons.addButton(
            "What data is sent?", QDialogButtonBox.HelpRole)
        self._info_btn.clicked.connect(self._show_info)
        form.addRow(buttons)

    def _show_info(self) -> None:
        QMessageBox.information(self, "How the AI Assistant Works", _INFO_TEXT)

    def _fetch_models(self) -> None:
        config = ai.LLMConfig(
            base_url=self._base_url.text().strip() or ai.DEFAULT_BASE_URL,
            api_key=self._api_key.text().strip() or None,
        )
        self._fetch_models_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            models = ai.list_models(config)
        except ai.LLMError as exc:
            QMessageBox.warning(self, "Fetch Models", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._fetch_models_btn.setEnabled(True)

        if not models:
            QMessageBox.information(
                self, "Fetch Models", "The server returned no models.")
            return

        current = self._model.currentText()
        self._model.clear()
        self._model.addItems(models)
        self._model.setCurrentText(current if current in models else models[0])

    def _save(self) -> None:
        settings = QSettings(_ORG, _APP)
        settings.setValue(
            "ai/base_url", self._base_url.text().strip() or ai.DEFAULT_BASE_URL)
        settings.setValue(
            "ai/model", self._model.currentText().strip() or ai.DEFAULT_MODEL)
        settings.setValue("ai/api_key", self._api_key.text().strip())
        self.accept()
