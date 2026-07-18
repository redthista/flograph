"""AI Assistant settings dialog (Tools > AI Assistant Settings…).

Persists the local-LLM connection (base URL, model, optional API key) via
QSettings, under the same "flograph"/"flograph" org/app used everywhere
else in the UI. load_llm_config() is the read side other UI code calls
before firing an "Ask AI" request.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
)

from flograph.ai import DEFAULT_BASE_URL, DEFAULT_MODEL, LLMConfig

_ORG = "flograph"
_APP = "flograph"


def load_llm_config() -> LLMConfig:
    settings = QSettings(_ORG, _APP)
    return LLMConfig(
        base_url=settings.value("ai/base_url", DEFAULT_BASE_URL, type=str),
        model=settings.value("ai/model", DEFAULT_MODEL, type=str),
        api_key=settings.value("ai/api_key", "", type=str) or None,
    )


class AiSettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI Assistant Settings")
        self.resize(440, 160)

        config = load_llm_config()

        self._base_url = QLineEdit(config.base_url)
        self._base_url.setPlaceholderText(DEFAULT_BASE_URL)
        self._model = QLineEdit(config.model)
        self._model.setPlaceholderText(DEFAULT_MODEL)
        self._api_key = QLineEdit(config.api_key or "")
        self._api_key.setPlaceholderText("(optional — most local servers don't need one)")
        self._api_key.setEchoMode(QLineEdit.Password)

        form = QFormLayout(self)
        form.addRow("Base URL", self._base_url)
        form.addRow("Model", self._model)
        form.addRow("API key", self._api_key)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _save(self) -> None:
        settings = QSettings(_ORG, _APP)
        settings.setValue(
            "ai/base_url", self._base_url.text().strip() or DEFAULT_BASE_URL)
        settings.setValue(
            "ai/model", self._model.text().strip() or DEFAULT_MODEL)
        settings.setValue("ai/api_key", self._api_key.text().strip())
        self.accept()
