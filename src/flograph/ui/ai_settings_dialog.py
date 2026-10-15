"""AI Assistant settings dialog (Tools > AI Assistant Settings…).

Edits the named AI connections (`flograph.llm.profiles`) — *Local Ollama*,
*Work gateway*, *Anthropic* — and which one is in use. Each has its wire
format, address, model, key and request options, plus where it is (this
PC or online) and the most the Flo Assistant may see of your data over
it. Keys go to the system keychain (`flograph.llm.keys`), never into the
profiles file or QSettings.

Nothing is written until Save: the dialog edits copies, so Cancel — or
deleting a connection and then cancelling — leaves everything as it was.

load_llm_config() is the read side Ask AI calls before a request. The
first read on a machine that predates profiles migrates the single
connection that used to live in QSettings (`ai/*`) into a profile, and
moves its key into the keychain.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QWidget,
)

from flograph import ai
from flograph.llm import keys, profiles, wire
from flograph.llm.profiles import Profile, ProfileSet

_ORG = "flograph"
_APP = "flograph"

_LOCAL_COLOUR = "#4caf50"
_ONLINE_COLOUR = "#e0a030"

_INFO_TEXT = """\
Each connection is one AI server. The one showing when you press Save is \
the one flograph uses. Requests go straight to its Base URL; nothing passes \
through a flograph-run server.

When you click "Ask AI" on a node, three things are sent:

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
will be included — it's part of the source code sent to the server.

"Most the assistant may see" is for the Flo Assistant: it caps how much of \
your data that assistant may be shown over this connection — from the flow \
alone up to real rows. A server on this PC defaults to anything; an online \
one defaults to column names and types, and has to be raised on purpose.

API keys are kept in your system keychain (Windows Credential Manager, the \
macOS Keychain, or the Secret Service on Linux), never in a settings file."""


def _settings() -> QSettings:
    return QSettings(_ORG, _APP)


def _profile_from_legacy(settings: QSettings) -> Profile:
    """The single connection QSettings used to hold, as a profile."""
    base = settings.value("ai/base_url", ai.DEFAULT_BASE_URL, type=str)
    profile = Profile(
        provider=settings.value("ai/provider", "openai", type=str),
        base_url=base,
        model=settings.value("ai/model", ai.DEFAULT_MODEL, type=str),
        verify_ssl=settings.value("ai/verify_ssl", True, type=bool),
    )
    if profile.provider not in wire.PROVIDERS:
        profile.provider = "openai"
    profile.name = ("Local server" if profile.detected_local()
                    else profiles.url_host(base) or "AI server")
    return profile


def load_profiles(store: keys.KeyStore | None = None) -> ProfileSet:
    """The saved connections, migrating the pre-profile one on first use."""
    if profiles.exists():
        return profiles.load()
    settings = _settings()
    profile = _profile_from_legacy(settings)
    profile_set = ProfileSet([profile], profile.id)
    legacy_key = settings.value("ai/api_key", "", type=str) or ""
    profiles.save(profile_set)
    if legacy_key:
        try:
            (store or keys.default_store()).set(profile.key_name, legacy_key)
        except keys.KeyStoreError:
            return profile_set  # keep it where it was; key_for reads it there
        settings.remove("ai/api_key")
    return profile_set


def key_for(profile: Profile, store: keys.KeyStore | None = None) -> str:
    """The profile's key, or "" — never raises, Ask AI must still try."""
    try:
        key = (store or keys.default_store()).get(profile.key_name)
    except keys.KeyStoreError:
        key = ""
    if not key:
        # A key the keychain refused during migration stays in QSettings.
        key = _settings().value("ai/api_key", "", type=str) or ""
    return key


def load_llm_config() -> ai.LLMConfig:
    """The active connection, as Ask AI's request settings."""
    profile = load_profiles().active()
    try:
        extra = profile.extra()
    except wire.LLMError:
        extra = {}  # Save refuses malformed JSON; only a hand edit gets here
    return ai.LLMConfig(
        base_url=profile.base_url,
        model=profile.model or ai.DEFAULT_MODEL,
        api_key=key_for(profile) or None,
        verify_ssl=profile.verify_ssl,
        provider=profile.provider,
        timeout=profile.timeout,
        max_tokens=profile.max_tokens,
        thinking=profile.thinking,
        extra=extra,
    )


class AiSettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI Assistant Settings")
        self.resize(560, 420)

        self._store = keys.default_store()
        loaded = load_profiles(self._store)
        # Copies: the dialog edits these and writes nothing until Save.
        self._profiles: list[Profile] = [p.copy() for p in loaded.profiles]
        self._current_id = loaded.active().id
        self._keys: dict[str, str] = {}       # profile id -> key as typed
        self._saved_keys: dict[str, str] = {}  # profile id -> key as loaded
        self._deleted: list[Profile] = []
        self._loading = False

        # -- which connection -----------------------------------------------
        self._profile_combo = QComboBox()
        self._profile_combo.setToolTip(
            "The connection showing when you press Save is the one in use")
        self._new_btn = QPushButton("New")
        self._dup_btn = QPushButton("Duplicate")
        self._del_btn = QPushButton("Delete")
        self._new_btn.clicked.connect(self._new_profile)
        self._dup_btn.clicked.connect(self._duplicate_profile)
        self._del_btn.clicked.connect(self._delete_profile)
        picker = QHBoxLayout()
        picker.addWidget(self._profile_combo, 1)
        for button in (self._new_btn, self._dup_btn, self._del_btn):
            picker.addWidget(button)

        self._name = QLineEdit()
        self._name.textEdited.connect(self._rename_current)

        # -- the server -----------------------------------------------------
        # Both formats answer GET /models identically, so fetching models
        # proves nothing about which one the server's chat endpoint speaks.
        self._provider = QComboBox()
        self._provider.addItem(
            "OpenAI-compatible  (/chat/completions)", "openai")
        self._provider.addItem("Anthropic-compatible  (/messages)", "anthropic")
        self._provider.setToolTip(
            "The wire format the server speaks. Ollama, LM Studio, vLLM, "
            "OpenAI, OpenRouter and most corporate gateways are "
            "OpenAI-compatible; the Anthropic API and Anthropic-style "
            "proxies are the other.")

        self._base_url = QLineEdit()
        self._base_url.setPlaceholderText(
            "blank = the official endpoint for this format")
        self._base_url.textChanged.connect(self._refresh_where)
        self._provider.currentIndexChanged.connect(self._refresh_where)

        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.setInsertPolicy(QComboBox.NoInsert)
        self._fetch_models_btn = QPushButton("Fetch Models")
        self._fetch_models_btn.setToolTip(
            "Query the server's /models endpoint, using the Base URL and "
            "API key above")
        self._fetch_models_btn.clicked.connect(self._fetch_models)
        model_row = QHBoxLayout()
        model_row.addWidget(self._model, 1)
        model_row.addWidget(self._fetch_models_btn)

        self._api_key = QLineEdit()
        self._api_key.setPlaceholderText(
            "(optional — most local servers don't need one)")
        self._api_key.setEchoMode(QLineEdit.Password)
        self._key_where = QLabel()
        self._key_where.setWordWrap(True)
        self._key_where.setStyleSheet("color: palette(mid);")

        self._verify_ssl = QCheckBox("Verify SSL certificates")
        self._verify_ssl.setToolTip(
            "Uncheck only if the Base URL uses a self-signed or otherwise "
            "untrusted certificate (e.g. behind a corporate proxy). This "
            "makes the connection vulnerable to interception.")

        # -- request options --------------------------------------------------
        self._max_tokens = QSpinBox()
        self._max_tokens.setRange(16, 1_000_000)
        self._max_tokens.setSingleStep(1024)
        self._thinking = QComboBox()
        self._thinking.addItems(wire.THINKING_OPTIONS)
        self._thinking.setToolTip(
            "Ask a reasoning model to stop thinking, or to think less. "
            "'default' sends nothing. openai format sends OpenRouter's "
            "'reasoning' field; anthropic format sends Anthropic's "
            "'thinking' block, so 'off' is already the default there.")
        self._extra = QPlainTextEdit()
        self._extra.setPlaceholderText('{"provider": {"order": ["deepinfra"]}}')
        self._extra.setFixedHeight(56)
        self._extra.setToolTip(
            "A JSON object merged into every request last, so it wins over "
            "everything above — for anything a gateway wants that flograph "
            "has never heard of.")

        self._tool_mode = QComboBox()
        self._tool_mode.addItem("Automatic", "auto")
        self._tool_mode.addItem("The server's tool API", "native")
        self._tool_mode.addItem("JSON in the reply text", "json")
        self._tool_mode.setToolTip(
            "How the Flo Assistant asks this model to use its tools. "
            "Automatic uses the server's tool API and falls back to JSON in "
            "the reply when the server refuses it. Choose JSON for a small "
            "local model that has tools but uses them badly.")

        # -- where the data goes ------------------------------------------------
        self._location = QComboBox()
        self._location.addItem("Automatic", "auto")
        self._location.addItem("This PC", "local")
        self._location.addItem("Online", "online")
        self._location.setToolTip(
            "Whether this server is on this computer. Automatic decides "
            "from the Base URL: only localhost counts — a server elsewhere "
            "on your network is still another machine.")
        self._location.currentIndexChanged.connect(self._refresh_where)
        self._where = QLabel()
        self._where_warning = QLabel()
        self._where_warning.setWordWrap(True)
        where_row = QHBoxLayout()
        where_row.addWidget(self._location)
        where_row.addWidget(self._where, 1)

        self._ceiling = QComboBox()
        self._ceiling.setToolTip(
            "The most the Flo Assistant may be shown of your data over this "
            "connection. A chat can always ask for less, never more.")
        ceiling_note = QLabel(
            "For the Flo Assistant. Ask AI only ever sends the node's code.")
        ceiling_note.setStyleSheet("color: palette(mid);")

        self._test_btn = QPushButton("Send Test Message")
        self._test_btn.setToolTip(
            "Send one short message to the chat endpoint — the request "
            "\"Ask AI\" actually makes, which fetching models does not test")
        self._test_btn.clicked.connect(self._test_chat)

        form = QFormLayout(self)
        form.addRow("Connection", picker)
        form.addRow("Name", self._name)
        form.addRow("API format", self._provider)
        form.addRow("Base URL", self._base_url)
        form.addRow("Model", model_row)
        form.addRow("API key", self._api_key)
        form.addRow("", self._key_where)
        form.addRow("", self._verify_ssl)
        form.addRow("Max tokens", self._max_tokens)
        form.addRow("Thinking", self._thinking)
        form.addRow("Extra request JSON", self._extra)
        form.addRow("Tool calling", self._tool_mode)
        form.addRow("Server is on", where_row)
        form.addRow("", self._where_warning)
        form.addRow("Most the assistant\nmay see", self._ceiling)
        form.addRow("", ceiling_note)
        form.addRow("", self._test_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self._info_btn = buttons.addButton(
            "What data is sent?", QDialogButtonBox.HelpRole)
        self._info_btn.clicked.connect(self._show_info)
        form.addRow(buttons)

        self._fill_combo()
        self._profile_combo.currentIndexChanged.connect(self._switch_profile)
        self._show(self._current())

    # -- the profile list --------------------------------------------------------

    def _current(self) -> Profile:
        return next(p for p in self._profiles if p.id == self._current_id)

    def _fill_combo(self) -> None:
        self._loading = True
        self._profile_combo.clear()
        for profile in self._profiles:
            self._profile_combo.addItem(profile.name, profile.id)
        self._profile_combo.setCurrentIndex(
            self._profile_combo.findData(self._current_id))
        self._loading = False
        self._del_btn.setEnabled(len(self._profiles) > 1)

    def _switch_profile(self, index: int) -> None:
        if self._loading or index < 0:
            return
        self._commit_form()
        self._current_id = self._profile_combo.itemData(index)
        self._show(self._current())

    def _rename_current(self, text: str) -> None:
        self._current().name = text
        index = self._profile_combo.findData(self._current_id)
        self._profile_combo.setItemText(index, text or "(unnamed)")

    def _add(self, profile: Profile, key: str = "") -> None:
        self._commit_form()
        self._profiles.append(profile)
        self._keys[profile.id] = key
        self._saved_keys[profile.id] = ""
        self._current_id = profile.id
        self._fill_combo()
        self._show(profile)
        self._name.setFocus()
        self._name.selectAll()

    def _new_profile(self) -> None:
        self._add(Profile(name="New connection"))

    def _duplicate_profile(self) -> None:
        self._commit_form()
        source = self._current()
        self._add(source.copy(id=profiles.new_id(), name=f"{source.name} copy"),
                  self._keys.get(source.id, ""))

    def _delete_profile(self) -> None:
        if len(self._profiles) <= 1:
            return
        gone = self._current()
        index = self._profiles.index(gone)
        self._profiles.remove(gone)
        self._deleted.append(gone)
        self._current_id = self._profiles[max(0, index - 1)].id
        self._fill_combo()
        self._show(self._current())

    # -- form <-> profile ----------------------------------------------------------

    def _key_of(self, profile: Profile) -> str:
        if profile.id not in self._keys:
            try:
                stored = self._store.get(profile.key_name)
            except keys.KeyStoreError as exc:
                stored = ""
                self._key_where.setText(str(exc))
            key = stored
            if not key and profile.id == self._current_id:
                # A key the keychain refused during migration is still in
                # QSettings. Show it, and leave it counted as unsaved so
                # Save moves it into the keychain before clearing QSettings.
                key = key_for(profile, self._store)
            self._keys[profile.id] = key
            self._saved_keys[profile.id] = stored
        return self._keys[profile.id]

    def _show(self, profile: Profile) -> None:
        self._loading = True
        self._name.setText(profile.name)
        index = self._provider.findData(profile.provider)
        self._provider.setCurrentIndex(max(index, 0))
        self._base_url.setText(profile.base_url)
        self._model.clear()
        self._model.addItem(profile.model)
        self._model.setCurrentText(profile.model)
        self._key_where.setText(
            f"Kept in {self._store.where}." if self._store.secure else
            f"⚠ No system keychain found — kept in {self._store.where}. "
            "Install the 'keyring' package to use your system keychain.")
        self._api_key.setText(self._key_of(profile))
        self._verify_ssl.setChecked(profile.verify_ssl)
        self._max_tokens.setValue(int(profile.max_tokens))
        self._thinking.setCurrentText(profile.thinking or "default")
        self._extra.setPlainText(profile.extra_json or "")
        self._tool_mode.setCurrentIndex(
            max(self._tool_mode.findData(profile.tool_mode), 0))
        self._location.setCurrentIndex(
            max(self._location.findData(profile.location), 0))
        self._loading = False
        self._refresh_where()
        self._ceiling.setCurrentIndex(
            0 if profile.ceiling is None else profile.ceiling + 1)

    def _commit_form(self) -> None:
        """The form's values into the profile being shown."""
        profile = self._current()
        profile.name = self._name.text().strip() or profile.name
        profile.provider = self._provider.currentData()
        profile.base_url = self._base_url.text().strip()
        profile.model = self._model.currentText().strip()
        profile.verify_ssl = self._verify_ssl.isChecked()
        profile.max_tokens = self._max_tokens.value()
        profile.thinking = self._thinking.currentText()
        profile.extra_json = self._extra.toPlainText().strip()
        profile.tool_mode = self._tool_mode.currentData()
        profile.location = self._location.currentData()
        profile.ceiling = self._ceiling.currentData()
        self._keys[profile.id] = self._api_key.text().strip()

    def _form_profile(self) -> Profile:
        """The profile as the form currently reads, without committing."""
        return self._current().copy(
            provider=self._provider.currentData(),
            base_url=self._base_url.text().strip(),
            location=self._location.currentData() or "auto")

    def _refresh_where(self, *_args) -> None:
        if self._loading:
            return
        profile = self._form_profile()
        detected = "this PC" if profile.detected_local() else "online"
        self._location.setItemText(0, f"Automatic ({detected})")
        colour = _LOCAL_COLOUR if profile.is_local() else _ONLINE_COLOUR
        self._where.setText(
            f'<span style="color:{colour}">●</span> {profile.where_label()}')
        if profile.location == "local" and not profile.detected_local():
            host = profiles.url_host(profile.base_url) or "another server"
            self._where_warning.setText(
                f"⚠ The Base URL isn't this computer — anything sent goes to "
                f"{host}. Only choose This PC for a server you run yourself.")
            self._where_warning.show()
        else:
            self._where_warning.hide()

        # The "Default" entry names what the default currently is, which
        # follows where the server is.
        chosen = self._ceiling.currentData() if self._ceiling.count() else None
        had_items = self._ceiling.count() > 0
        self._ceiling.blockSignals(True)
        self._ceiling.clear()
        self._ceiling.addItem(
            f"Default — {profiles.level_label(profile.default_ceiling())}", None)
        for index, (_key, label) in enumerate(profiles.LEVELS):
            self._ceiling.addItem(label, index)
        self._ceiling.setCurrentIndex(
            0 if (chosen is None or not had_items) else chosen + 1)
        self._ceiling.blockSignals(False)

    # -- buttons -------------------------------------------------------------------

    def _show_info(self) -> None:
        QMessageBox.information(self, "How the AI Assistant Works", _INFO_TEXT)

    def _current_config(self) -> ai.LLMConfig:
        """The settings as typed, not as last saved — so both buttons test
        what the user is about to save."""
        profile = self._form_profile().copy(
            extra_json=self._extra.toPlainText().strip())
        return ai.LLMConfig(
            base_url=self._base_url.text().strip(),
            model=self._model.currentText().strip() or ai.DEFAULT_MODEL,
            api_key=self._api_key.text().strip() or None,
            verify_ssl=self._verify_ssl.isChecked(),
            provider=self._provider.currentData(),
            max_tokens=self._max_tokens.value(),
            thinking=self._thinking.currentText(),
            extra=profile.extra(),
        )

    def _test_chat(self) -> None:
        """The one check that exercises what "Ask AI" does: a real
        completion. A server can list models and still refuse to chat."""
        self._test_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            config = self._current_config()
            reply = ai.chat_completion(
                [{"role": "user", "content": "Reply with the word OK."}],
                config)
        except (ai.LLMError, ValueError) as exc:
            QMessageBox.warning(self, "Send Test Message", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._test_btn.setEnabled(True)
        QMessageBox.information(
            self, "Send Test Message",
            f"{config.model} answered:\n\n{reply.strip()[:200]}")

    def _fetch_models(self) -> None:
        self._fetch_models_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            models = ai.list_models(self._current_config())
        except (ai.LLMError, ValueError) as exc:
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
        self._commit_form()
        for profile in self._profiles:
            if not profile.model:
                profile.model = ai.DEFAULT_MODEL
            try:
                profile.extra()
            except wire.LLMError as exc:
                self._profile_combo.setCurrentIndex(
                    self._profile_combo.findData(profile.id))
                QMessageBox.warning(self, "AI Assistant Settings", str(exc))
                return
        try:
            for profile in self._profiles:
                key = self._keys.get(profile.id)
                if key is not None and key != self._saved_keys.get(profile.id):
                    self._store.set(profile.key_name, key)
            for profile in self._deleted:
                self._store.delete(profile.key_name)
        except keys.KeyStoreError as exc:
            QMessageBox.warning(self, "AI Assistant Settings", str(exc))
            return
        profiles.save(ProfileSet(self._profiles, self._current_id))
        # Whatever the keychain now holds, the pre-profile copy is stale.
        _settings().remove("ai/api_key")
        self.accept()
