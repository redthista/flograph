"""Packages dialog: browse, install, upgrade and uninstall pip packages in
flograph's own environment (Tools > Manage Packages).

The installer (pip, or `uv pip` when the venv has no pip) runs as a
QProcess so the UI stays live and its output streams into the log pane.
Nodes import from this same environment, but "installed" and "usable
without a restart" are not the same thing: an upgrade cannot reach a module
the app has already imported, and a fresh install cannot reach a library
that checked for it at startup and cached its absence — pandas does exactly
that with pyarrow. Both cases are reported in the log.

Where installs come from is Settings ▸ Packages (AC1): an index URL and
hosts to trust, over pip's own settings. The dialog says which index is in
force, and where that came from, above the log.

An index that wants a user name and password gets them from a Sign In
window, not from a box under the log. A console can answer pip's prompt;
a pipe can't, because on Windows pip reads the password from the console
itself, and `uv pip` never asks at all. So when the index turns an install
away, the dialog stops the installer, asks, and runs the install again
with the login in the index URL — handed over in the installer's
environment, never its command line. The login lasts until flograph
closes, one per index host, and is never saved. None of it shows until a
private index is set: plain PyPI is the normal case.
"""
from __future__ import annotations

import importlib

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from flograph import packages

#: Settings ▸ Packages — the index an install uses, over pip's own settings
SETTINGS_INDEX_URL = "packages/index_url"
SETTINGS_TRUSTED_HOST = "packages/trusted_host"
#: Settings ▸ Packages — say, on opening a flow, when it needs something
#: that isn't installed (AC2). On by default: it only ever appears for a
#: flow that would fail without it.
SETTINGS_NOTIFY_MISSING = "packages/notify_missing"


def configured_index(settings) -> packages.PackageIndex:
    """flograph's own index setting — empty (and falsy) when none is set,
    which means "whatever pip is configured with"."""
    if settings is None:
        return packages.PackageIndex()
    return packages.PackageIndex(
        url=str(settings.value(SETTINGS_INDEX_URL, "") or ""),
        trusted_host=str(settings.value(SETTINGS_TRUSTED_HOST, "") or ""),
        source="Settings ▸ Packages")


def index_in_force(settings) -> str:
    """Where installs are coming from, as one line: the setting, pip's own
    config, uv's own, or PyPI."""
    configured = configured_index(settings)
    if not configured and packages.installer_kind() == "uv" \
            and packages.uv_has_own_index():
        return "uv's own index settings"
    return packages.describe_index(packages.effective_index(configured))


#: index host -> the login signed in with this session. In memory only:
#: a password never reaches QSettings or the disk.
_LOGINS: dict[str, packages.IndexLogin] = {}


class SignInDialog(QDialog):
    """User name and password for one index host."""

    def __init__(self, host: str, username: str = "", refused: bool = False,
                 parent=None, risk: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Sign In to Package Index")
        #: said before a password is typed, not after it has gone
        self.risk_label = QLabel("⚠ " + risk if risk else "")
        self.risk_label.setObjectName("sign_in_risk")
        self.risk_label.setTextFormat(Qt.PlainText)
        self.risk_label.setWordWrap(True)
        self.risk_label.setVisible(bool(risk))
        self.risk_label.setStyleSheet("color: #e0a030;")
        intro = QLabel(
            (f"{host} didn't accept that user name and token or password. "
             f"Try again — a token may have expired or been revoked."
             if refused else
             f"{host} asks you to sign in."))
        intro.setTextFormat(Qt.PlainText)
        intro.setWordWrap(True)
        self.user_edit = QLineEdit(username)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("token (recommended) or password")
        # a token rather than the password: it opens only the index, is
        # revoked on its own, and a wrong one can't lock the Windows account
        hint = QLabel(
            "JFrog: paste an identity or reference token from your JFrog "
            "profile (Edit Profile ▸ Generate an Identity Token). Safer than "
            "your password: it only opens JFrog, and it can be revoked on "
            "its own. Your password works too.\n"
            "Kept until flograph closes; never saved.")
        hint.setTextFormat(Qt.PlainText)
        hint.setWordWrap(True)
        form = QFormLayout()
        form.addRow("User name:", self.user_edit)
        form.addRow("Password or token:", self.password_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Sign In")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.risk_label)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        (self.password_edit if username else self.user_edit).setFocus()
        # width only: the height follows the wrapped hint, which a height
        # taken from sizeHint() now — before wrapping — would cut short
        self.setMinimumWidth(400)

    def login(self) -> packages.IndexLogin:
        return packages.IndexLogin(self.user_edit.text().strip(),
                                   self.password_edit.text())


class PackagesDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Packages")
        self.resize(720, 560)
        self._process: QProcess | None = None
        #: the window's QSettings, where Settings ▸ Packages keeps the index
        self._settings = getattr(parent, "settings", None)
        #: the running install: its action and specs (to run again after a
        #: sign-in), everything it has printed, and the login it was sent
        self._run: tuple[str, list[str]] | None = None
        self._run_output = ""
        self._run_login: packages.IndexLogin | None = None
        self._stopped_for_login = False

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter installed packages…")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._apply_filter)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Package", "Version"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)

        self._install_edit = QLineEdit()
        self._install_edit.setPlaceholderText(
            "package to install, e.g. requests or polars==1.8")
        self._install_edit.returnPressed.connect(self._install)
        self._install_btn = QPushButton("Install")
        self._install_btn.clicked.connect(self._install)
        install_row = QHBoxLayout()
        install_row.addWidget(self._install_edit, 1)
        install_row.addWidget(self._install_btn)

        self._upgrade_btn = QPushButton("Upgrade Selected")
        self._upgrade_btn.clicked.connect(self._upgrade)
        self._uninstall_btn = QPushButton("Uninstall Selected")
        self._uninstall_btn.clicked.connect(self._uninstall)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel_process)
        buttons = QHBoxLayout()
        buttons.addWidget(self._upgrade_btn)
        buttons.addWidget(self._uninstall_btn)
        buttons.addStretch(1)
        buttons.addWidget(self._cancel_btn)
        buttons.addWidget(self._refresh_btn)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSizeF(9.0)
        self._log.setFont(font)

        self._status = QLabel()
        self._status.setTextFormat(Qt.PlainText)
        self._index_label = QLabel()
        self._index_label.setObjectName("packages_index_label")
        self._index_label.setTextFormat(Qt.PlainText)
        self._index_label.setWordWrap(True)
        self._index_label.setToolTip(
            "Set a private index in Settings ▸ Packages. Left blank, pip's "
            "own settings are used — pip.conf, PIP_INDEX_URL — and handed "
            "on to uv, which does not read them itself.")
        self._sign_in_btn = QPushButton("Sign In…")
        self._sign_in_btn.setToolTip(
            "Give a user name and a token (or password) for the index — for "
            "a JFrog or Artifactory that asks for one. Kept until flograph "
            "closes.")
        self._sign_in_btn.clicked.connect(self._toggle_sign_in)
        index_row = QHBoxLayout()
        index_row.addWidget(self._index_label, 1)
        index_row.addWidget(self._sign_in_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._filter)
        layout.addWidget(self._table, 3)
        layout.addLayout(install_row)
        layout.addLayout(buttons)
        layout.addWidget(self._log, 2)
        layout.addLayout(index_row)
        layout.addWidget(self._status)

        kind = packages.installer_kind()
        if kind is None:
            self._status.setText(
                "No installer available — no pip in this environment and no "
                "uv on PATH.")
            for btn in (self._install_btn, self._upgrade_btn,
                        self._uninstall_btn):
                btn.setEnabled(False)
        else:
            self._status.setText(f"Installer: {kind} — packages land in "
                                 f"flograph's own environment.")
        self._show_index()
        self.refresh()

    def _show_index(self) -> None:
        text = "Installs from: " + index_in_force(self._settings)
        login = self._login()
        if login:
            text += f" — signed in as {login.username}"
        self._index_label.setText(text)
        self._sign_in_btn.setText("Sign Out" if login else "Sign In…")
        # a private index is the exception, not the rule: with plain PyPI
        # there is nothing to sign in to, and no button to wonder about
        self._sign_in_btn.setVisible(bool(self._index_host()))

    # -------------------------------------------------------------- sign-in

    def _index_host(self) -> str:
        """The host a login would go to — "" when installs come from
        nowhere a login can be put (PyPI, a file:// index)."""
        index = packages.login_index(configured_index(self._settings))
        if index.url.strip().split(":", 1)[0].lower() not in ("http", "https"):
            return ""
        return packages.index_host(index.url)

    def _login_risk(self) -> str:
        """Why a password sent to this index could be read on the way,
        or "" — shown in the Sign In window before one is typed."""
        return packages.login_risk(
            packages.login_index(configured_index(self._settings)))

    def _login(self) -> packages.IndexLogin | None:
        return _LOGINS.get(self._index_host())

    def _toggle_sign_in(self) -> None:
        host = self._index_host()
        if host in _LOGINS:
            del _LOGINS[host]
            self._append_log(f"— signed out of {host} —")
        else:
            self._sign_in(host)
        self._show_index()

    def _sign_in(self, host: str, refused: bool = False) -> bool:
        """Ask for a login to `host` and keep it; False if none was given."""
        previous = _LOGINS.get(host)
        login = self._ask_login(
            host, previous.username if previous else "", refused)
        if not login:
            return False
        _LOGINS[host] = login
        self._append_log(f"— signed in to {host} as {login.username} —")
        return True

    def _ask_login(self, host: str, username: str,
                   refused: bool) -> packages.IndexLogin | None:
        """The Sign In window; a separate method so tests can answer it."""
        dialog = SignInDialog(host, username, refused, self,
                              risk=self._login_risk())
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.login() or None

    def showEvent(self, event) -> None:
        # the dialog is kept and reshown, and Settings may have changed
        # the index since it was last up
        self._show_index()
        super().showEvent(event)

    def prefill(self, names: list) -> None:
        """Put `names` in the install box, ready to install — what What
        This Flow Needs hands over. Nothing is installed until Install is
        pressed."""
        self._install_edit.setText(" ".join(names))
        self._install_edit.setFocus()

    # ---------------------------------------------------------------- table

    def refresh(self) -> None:
        self._table.setRowCount(0)
        for name, version in packages.list_installed():
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(name))
            self._table.setItem(row, 1, QTableWidgetItem(version))
        self._apply_filter(self._filter.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self._table.rowCount()):
            name = self._table.item(row, 0).text()
            self._table.setRowHidden(row, bool(needle) and needle not in name)

    def _selected_packages(self) -> list[str]:
        rows = {index.row() for index in self._table.selectedIndexes()}
        return [self._table.item(row, 0).text() for row in sorted(rows)]

    # -------------------------------------------------------------- actions

    def _install(self) -> None:
        spec = self._install_edit.text().strip()
        if spec:
            self._run_installer("install", spec.split())

    def _upgrade(self) -> None:
        selected = self._selected_packages()
        if selected:
            self._run_installer("upgrade", selected)

    def _uninstall(self) -> None:
        selected = self._selected_packages()
        if not selected:
            return
        core = [p for p in selected if p in packages.CORE_PACKAGES]
        if core:
            QMessageBox.warning(
                self, "Protected packages",
                f"flograph itself depends on: {', '.join(core)} — uninstalling "
                f"them would break the running app, so they are protected.")
            return
        answer = QMessageBox.question(
            self, "Uninstall packages",
            "Uninstall " + ", ".join(selected) + "?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._run_installer("uninstall", selected)

    # -------------------------------------------------------------- process

    @property
    def busy(self) -> bool:
        return (self._process is not None
                and self._process.state() != QProcess.NotRunning)

    def _run_installer(self, action: str, specs: list[str]) -> None:
        if self.busy:
            return
        login = self._login()
        index = configured_index(self._settings)
        try:
            argv = packages.build_command(action, specs, index=index,
                                          login=login)
            secret_env = packages.login_environment(action, index, login)
        except (ValueError, RuntimeError) as exc:
            self._append_log(f"error: {exc}")
            return
        self._run, self._run_output = (action, list(specs)), ""
        self._run_login, self._stopped_for_login = login, False
        self._append_log("$ " + packages.redact(" ".join(argv), login))
        if secret_env:
            self._append_log(f"  (signed in as {login.username}; the login "
                             f"goes to the installer privately, not on its "
                             f"command line)")
        self._set_busy(True)
        process = QProcess(self)
        if secret_env:
            # the login rides in the installer's environment, which only
            # this user can read — never in argv, which anyone can
            env = QProcessEnvironment.systemEnvironment()
            for name, value in secret_env.items():
                env.insert(name, value)
            process.setProcessEnvironment(env)
        process.readyReadStandardOutput.connect(
            lambda: self._on_output(process.readAllStandardOutput()))
        process.readyReadStandardError.connect(
            lambda: self._on_output(process.readAllStandardError()))
        process.finished.connect(
            lambda code, _status: self._on_finished(action, code))
        process.errorOccurred.connect(
            lambda _err: self._append_log(process.errorString()))
        self._process = process
        process.start(argv[0], argv[1:])

    def _on_output(self, data) -> None:
        text = bytes(data).decode(errors="replace")
        self._run_output += text
        self._append_log(packages.redact(text, self._run_login),
                         newline=False)
        # pip, wanting a login, prints its prompt and waits on input this
        # window can't give it: stop it, and ask for the login instead
        if (not self._stopped_for_login and self.busy
                and packages.asks_for_login(self._run_output[-500:])):
            self._stopped_for_login = True
            self._process.kill()

    def _on_finished(self, action: str, code: int) -> None:
        if action != "uninstall" and self._index_host() and (
                self._stopped_for_login
                or (code != 0 and packages.login_refused(self._run_output))):
            self._append_log("")
            self._append_log(f"— {action} stopped: the index asks you to "
                             f"sign in —")
            self._set_busy(False)
            # after this slot returns: a modal window opened from inside
            # QProcess.finished would run with the process still tearing down
            QTimer.singleShot(0, lambda: self._retry_after_sign_in(
                bool(self._run_login)))
            return
        self._append_log(f"— {action} "
                         f"{'finished' if code == 0 else f'failed ({code})'} —")
        if code == 0 and action == "install":
            # A directory Python has already listed keeps its cached
            # listing, so a package installed just now stays invisible to
            # import until the finders are told to look again.
            importlib.invalidate_caches()
            self._append_log(
                "note: restart flograph before using a package that was "
                "missing when it started — a library that checked for it at "
                "import time cached its absence and will misbehave rather "
                "than pick it up (pandas does this with pyarrow)")
        elif code == 0 and action in ("upgrade", "uninstall"):
            self._append_log(
                "note: modules already imported by the running app keep "
                "their old version until flograph is restarted")
        self._set_busy(False)
        self.refresh()

    def _retry_after_sign_in(self, refused: bool) -> None:
        """Ask for a login and, given one, run the stopped install again."""
        host = self._index_host()
        if not host or self._run is None:
            return
        signed_in = self._sign_in(host, refused=refused)
        self._show_index()
        if signed_in:
            self._run_installer(*self._run)
        else:
            self._append_log("— not signed in; nothing installed —")

    def _cancel_process(self) -> None:
        if self.busy:
            self._process.kill()

    def _set_busy(self, busy: bool) -> None:
        for btn in (self._install_btn, self._upgrade_btn,
                    self._uninstall_btn, self._refresh_btn):
            btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(busy)

    def _append_log(self, text: str, newline: bool = True) -> None:
        if newline:
            self._log.appendPlainText(text.rstrip("\n"))
        else:
            self._log.moveCursor(QTextCursor.End)
            self._log.insertPlainText(text)
            self._log.moveCursor(QTextCursor.End)

    def closeEvent(self, event) -> None:
        if self.busy:
            self._process.kill()
            self._process.waitForFinished(2000)
        super().closeEvent(event)
