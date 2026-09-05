"""Create a desktop shortcut that relaunches *this* flograph.

flograph is started in more than one way and the shortcut has to match the
one in front of the user, because they are not interchangeable: a one-file
bundle is a path to a .py that carries its own source, while a pip install
is `-m flograph` and has no path to point at. Both, though, run under one
particular interpreter — the venv the user already has PySide6 and pandas
in — so every shortcut this module writes names that interpreter
explicitly rather than trusting whatever `python` resolves to when the icon
is double-clicked.

The writers are per-platform because the file formats are: a real `.lnk` on
Windows (built through WScript.Shell, which is the only way to write one
without a dependency), a `.desktop` entry on Linux, a `.command` script on
macOS.
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha1
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QMessageBox, QVBoxLayout,
)

from ..paths import user_data_dir
from . import theme

# Windows only: keep the probe's console window from flashing up.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ------------------------------------------------------------ what to launch

@dataclass(frozen=True)
class Launch:
    """The command a shortcut should run, and why it looks like that."""

    argv: list[str]
    workdir: str | None
    kind: str          # "onefile" | "module" | "source"
    note: str          # one line for the dialog


def python_exe() -> str:
    """The interpreter to launch with — pythonw.exe where it exists, so a
    Windows shortcut doesn't drag a console window along behind the app."""
    exe = Path(sys.executable)
    if sys.platform == "win32":
        gui = exe.with_name("pythonw.exe")
        if gui.exists():
            return str(gui)
    return str(exe)


def onefile_path(main_module=None) -> str | None:
    """The path of the running single-file bundle, or None.

    The bundle unpacks itself to a temp dir that is deleted at exit, so the
    only durable thing to point a shortcut at is the .py the user was handed
    — which is `__main__` itself, identified by the base64 blob it carries.
    """
    module = main_module if main_module is not None else sys.modules.get("__main__")
    if module is None or not hasattr(module, "_BUNDLE_B64"):
        return None
    path = getattr(module, "__file__", None)
    return str(Path(path).resolve()) if path else None


def module_importable(python: str | None = None) -> bool:
    """Whether a *fresh* interpreter can `import flograph` on its own.

    PYTHONPATH is dropped for the probe: the shortcut will be double-clicked
    from a desktop that has no idea what this process's environment was, so
    anything that only works because of it is a false yes.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    try:
        proc = subprocess.run(
            [python or sys.executable, "-c",
             "import importlib.util,sys;"
             "sys.exit(0 if importlib.util.find_spec('flograph') else 1)"],
            env=env, timeout=30, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def source_launcher() -> str | None:
    """`<repo>/main.py` when running from an uninstalled checkout."""
    repo = Path(__file__).resolve().parent.parent.parent.parent
    launcher = repo / "main.py"
    return str(launcher) if launcher.exists() else None


def resolve_launch(project: str | None = None, *, main_module=None,
                   probe=None) -> Launch:
    """Work out how this flograph was started, and how to start it again."""
    python = python_exe()
    importable = probe if probe is not None else module_importable

    bundle = onefile_path(main_module)
    if bundle:
        argv, workdir, kind = [python, bundle], str(Path(bundle).parent), "onefile"
        note = f"Runs the one-file bundle {Path(bundle).name} with this environment's Python."
    elif importable(sys.executable):
        argv, workdir, kind = [python, "-m", "flograph"], None, "module"
        note = "Runs the installed flograph package with this environment's Python."
    elif (launcher := source_launcher()):
        argv, workdir, kind = [python, launcher], str(Path(launcher).parent), "source"
        note = ("flograph isn't installed in this environment, so the shortcut "
                f"runs the checkout's {Path(launcher).name} directly.")
    else:
        argv, workdir, kind = [python, "-m", "flograph"], None, "module"
        note = ("Couldn't confirm flograph is importable — the shortcut still "
                "runs `-m flograph`, so check it opens before relying on it.")

    if project:
        argv = [*argv, str(project)]
        workdir = str(Path(project).parent)
    return Launch(argv=argv, workdir=workdir, kind=kind, note=note)


def display_command(launch: Launch) -> str:
    """The command as the user would have to type it."""
    if sys.platform == "win32":
        return subprocess.list2cmdline(launch.argv)
    import shlex
    return shlex.join(launch.argv)


# ------------------------------------------------------------------ where to

@lru_cache(maxsize=1)
def desktop_dir() -> Path:
    """The user's Desktop, asking the platform rather than assuming ~/Desktop
    — it is redirected often enough (OneDrive, localised names, XDG) that a
    guess would quietly write the shortcut where nobody looks."""
    if sys.platform == "win32":
        resolved = _windows_shell_desktop()
        if resolved:
            return resolved
        onedrive = os.environ.get("OneDrive") or os.environ.get("ONEDRIVE")
        if onedrive and (Path(onedrive) / "Desktop").is_dir():
            return Path(onedrive) / "Desktop"
    elif sys.platform.startswith("linux"):
        xdg = _xdg_desktop()
        if xdg:
            return xdg
    return Path.home() / "Desktop"


def _windows_shell_desktop() -> Path | None:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    path = proc.stdout.strip()
    return Path(path) if proc.returncode == 0 and path else None


def _xdg_desktop() -> Path | None:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    dirs_file = config / "user-dirs.dirs"
    try:
        text = dirs_file.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if not line.startswith("XDG_DESKTOP_DIR="):
            continue
        value = line.split("=", 1)[1].strip().strip('"')
        value = value.replace("$HOME", str(Path.home()))
        return Path(value)
    return None


_BAD_NAME_CHARS = '\\/:*?"<>|\n\r\t'


def clean_name(name: str) -> str:
    """A file-name-safe shortcut name (empty if nothing usable is left)."""
    cleaned = "".join(" " if c in _BAD_NAME_CHARS else c for c in name).strip()
    return cleaned.rstrip(".")


def shortcut_suffix() -> str:
    if sys.platform == "win32":
        return ".lnk"
    if sys.platform == "darwin":
        return ".command"
    return ".desktop"


def shortcut_path(name: str) -> Path:
    return desktop_dir() / (clean_name(name) + shortcut_suffix())


# --------------------------------------------------------------------- icon

_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _paint_mark(size: int) -> QImage:
    """The flograph app mark — the same linked-nodes-on-a-tile logo the
    window and taskbar icon use, so the desktop shortcut matches it.

    QImage rather than QPixmap on purpose: this is a raster file being
    written, not something being shown, and QImage needs no window system.
    """
    from .window_frame import paint_app_mark

    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    paint_app_mark(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def _mark_sizes(sizes=_ICON_SIZES) -> list[tuple[int, QImage]]:
    """The mark at every size an icon file wants, scaled down from one big
    render rather than painted small: at 16px the tile's border and the two
    node dots are sub-pixel, and a smooth downscale of the real drawing
    reads far better than antialiasing that geometry directly."""
    master = _paint_mark(max(sizes))
    return [(s, master if s == master.width()
             else master.scaled(s, s, Qt.KeepAspectRatio,
                                Qt.SmoothTransformation))
            for s in sizes]


def _png_bytes(image: QImage) -> bytes:
    # the QByteArray has to outlive the QBuffer that writes into it — a
    # temporary here is collected out from under Qt and takes the process
    # with it
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def _dib_bytes(image: QImage) -> bytes:
    """One icon image in the old BMP form: a BITMAPINFOHEADER, the pixels
    bottom-up as BGRA, then an empty 1-bit mask.

    Every size below 256 is written this way rather than as a PNG, because
    a PNG-only .ico is the form parts of the Windows shell quietly decline
    to read — and when the shell can't read the icon a shortcut falls back
    to its target's, which is why one can come out wearing Python's logo.
    """
    img = image.convertToFormat(QImage.Format_ARGB32)
    w, h, stride = img.width(), img.height(), img.bytesPerLine()
    raw = bytes(img.constBits())
    # ARGB32 is a little-endian 32-bit int, so its bytes are already BGRA;
    # only the row order differs from what a DIB wants.
    xor = b"".join(raw[y * stride:y * stride + w * 4] for y in range(h - 1, -1, -1))
    # 32-bit icons carry their transparency in the alpha channel, so the
    # mask is all-zero — present only because the format demands it.
    mask = bytes(((w + 31) // 32) * 4 * h)
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                         len(xor) + len(mask), 0, 0, 0, 0)
    return header + xor + mask


def _ico_bytes(entries: list[tuple[int, bytes]]) -> bytes:
    """Pack `(size, image bytes)` pairs into an .ico — a six-byte header, a
    sixteen-byte directory row each, then the images. A 256px entry records
    its size as 0, which is how the format spells "256"."""
    offset = 6 + 16 * len(entries)
    rows = []
    for size, payload in entries:
        dim = 0 if size >= 256 else size
        rows.append(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                                len(payload), offset))
        offset += len(payload)
    return (struct.pack("<HHH", 0, 1, len(entries)) + b"".join(rows)
            + b"".join(payload for _, payload in entries))


def _icon_bytes() -> bytes:
    """The icon file for this platform: a multi-size .ico on Windows, a
    plain 256px PNG everywhere else (both Linux and macOS scale one)."""
    images = _mark_sizes()
    if sys.platform != "win32":
        return _png_bytes(images[-1][1])
    return _ico_bytes([(size, _png_bytes(image) if size >= 256
                        else _dib_bytes(image)) for size, image in images])


def ensure_icon(directory: Path | None = None) -> Path | None:
    """Write the icon the shortcut points at, returning its path (or None if
    it can't be painted — a shortcut without an icon still works).

    The name carries a digest of the picture. Windows keys its shell icon
    cache on the icon's *path*, and re-reads that path grudgingly: an icon
    rewritten in place leaves every shortcut already on the desktop showing
    the picture it had the first time. A changed mark lands at a name no
    cache has an entry for, so it shows up straight away.
    """
    target_dir = directory or user_data_dir()
    suffix = ".ico" if sys.platform == "win32" else ".png"
    try:
        blob = _icon_bytes()
        if not blob:
            return None
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"flograph-{sha1(blob).hexdigest()[:8]}{suffix}"
        if not path.exists():
            path.write_bytes(blob)
        _sweep_old_icons(target_dir, keep=path)
    except (OSError, RuntimeError):
        return None
    return path


def _sweep_old_icons(directory: Path, keep: Path) -> None:
    """Drop the icons earlier versions of the mark left behind. The
    unversioned `flograph.ico` older releases wrote is left alone: a
    shortcut made back then still points at it."""
    for stale in directory.glob("flograph-*"):
        if stale != keep and stale.suffix in (".ico", ".png"):
            try:
                stale.unlink()
            except OSError:
                pass


# ------------------------------------------------------------------- writers

_PS_CREATE = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($env:FLOGRAPH_LNK_PATH)
$link.TargetPath = $env:FLOGRAPH_LNK_TARGET
$link.Arguments = $env:FLOGRAPH_LNK_ARGS
if ($env:FLOGRAPH_LNK_WORKDIR) { $link.WorkingDirectory = $env:FLOGRAPH_LNK_WORKDIR }
if ($env:FLOGRAPH_LNK_ICON) { $link.IconLocation = $env:FLOGRAPH_LNK_ICON }
$link.Description = 'flograph'
$link.Save()
"""


def _write_windows(path: Path, launch: Launch, icon: Path | None) -> Path:
    env = dict(os.environ)
    env.update({
        "FLOGRAPH_LNK_PATH": str(path),
        "FLOGRAPH_LNK_TARGET": launch.argv[0],
        "FLOGRAPH_LNK_ARGS": subprocess.list2cmdline(launch.argv[1:]),
        "FLOGRAPH_LNK_WORKDIR": launch.workdir or "",
        # WScript.Shell wants "path,index"; a bare path is not the
        # documented form and the shell can decline to take it.
        "FLOGRAPH_LNK_ICON": f"{icon},0" if icon else "",
    })
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-Command", "-"],
            input=_PS_CREATE, env=env, capture_output=True, text=True,
            timeout=60, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return _write_windows_cmd(path, launch)
    if proc.returncode != 0 or not path.exists():
        return _write_windows_cmd(path, launch)
    return path


def _write_windows_cmd(path: Path, launch: Launch) -> Path:
    """Fallback when WScript.Shell is unavailable (locked-down PowerShell):
    a .cmd is not as tidy as a .lnk but it double-clicks the same."""
    fallback = path.with_suffix(".cmd")
    lines = ["@echo off"]
    if launch.workdir:
        lines.append(f'cd /d "{launch.workdir}"')
    lines.append('start "" ' + subprocess.list2cmdline(launch.argv))
    try:
        fallback.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"couldn't write the shortcut: {exc}") from exc
    return fallback


def _write_linux(path: Path, launch: Launch, icon: Path | None, name: str) -> Path:
    import shlex
    exec_line = shlex.join(launch.argv).replace("%", "%%")
    entry = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        "Comment=flograph — visual node-based Python",
        f"Exec={exec_line}",
        "Terminal=false",
        "Categories=Development;Science;",
        # matches QApplication.setDesktopFileName, so a dock shows the
        # running window under this launcher and its icon, not a
        # generic Python one beside it
        "StartupWMClass=flograph",
    ]
    if launch.workdir:
        entry.append(f"Path={launch.workdir}")
    if icon:
        entry.append(f"Icon={icon}")
    path.write_text("\n".join(entry) + "\n", encoding="utf-8")
    path.chmod(0o755)
    # GNOME won't launch a .desktop it hasn't been told to trust; harmless
    # everywhere else, and a missing gio is not an error worth reporting.
    try:
        subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass
    return path


def _write_macos(path: Path, launch: Launch) -> Path:
    import shlex
    lines = ["#!/bin/sh"]
    if launch.workdir:
        lines.append(f"cd {shlex.quote(launch.workdir)}")
    lines.append("exec " + shlex.join(launch.argv))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def create_shortcut(name: str, launch: Launch, *, icon: Path | None = None) -> Path:
    """Write the shortcut and return the file it actually created."""
    safe = clean_name(name)
    if not safe:
        raise ValueError("the shortcut needs a name")
    folder = desktop_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (safe + shortcut_suffix())
    try:
        if sys.platform == "win32":
            return _write_windows(path, launch, icon)
        if sys.platform == "darwin":
            return _write_macos(path, launch)
        return _write_linux(path, launch, icon, safe)
    except OSError as exc:
        raise RuntimeError(f"couldn't write {path}: {exc}") from exc


# -------------------------------------------------------------------- dialog

class ShortcutDialog(QDialog):
    """Name it, decide whether it opens the current project, create it."""

    def __init__(self, parent=None, project_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Create Desktop Shortcut")
        self._project_path = project_path
        self.created_path: Path | None = None

        default = Path(project_path).stem if project_path else "flograph"
        self.name_edit = QLineEdit(default, self)
        self.open_project = QCheckBox(
            f"Open {Path(project_path).name} on launch" if project_path
            else "Open the current project on launch", self)
        self.open_project.setChecked(bool(project_path))
        self.open_project.setEnabled(bool(project_path))
        if not project_path:
            self.open_project.setToolTip(
                "Save the project first and the shortcut can open it.")

        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        # selectable: the resolved command is worth copying out when a
        # shortcut has to be recreated by hand elsewhere
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary.setStyleSheet(f"color: {theme.NODE_SUBTEXT.name()};")

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("", self.open_project)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel, self)
        self.create_button = buttons.addButton("Create", QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self._create)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.summary)
        layout.addWidget(buttons)

        self.name_edit.textChanged.connect(self._refresh)
        self.open_project.toggled.connect(self._refresh)
        self._refresh()

    # -- state

    def launch(self) -> Launch:
        project = (self._project_path
                   if self._project_path and self.open_project.isChecked() else None)
        return resolve_launch(project)

    def _refresh(self) -> None:
        launch = self.launch()
        name = clean_name(self.name_edit.text())
        self.create_button.setEnabled(bool(name))
        target = shortcut_path(name) if name else None
        lines = [launch.note,
                 f"Runs:  {display_command(launch)}"]
        if target:
            lines.append(f"Creates:  {target}")
        self.summary.setText("\n".join(lines))

    # -- action

    def _create(self) -> None:
        name = clean_name(self.name_edit.text())
        if not name:
            return
        target = shortcut_path(name)
        if target.exists():
            answer = QMessageBox.question(
                self, "Replace shortcut?",
                f"{target.name} is already on the desktop. Replace it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        try:
            path = create_shortcut(name, self.launch(), icon=ensure_icon())
        except (RuntimeError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Couldn't create the shortcut", str(exc))
            return
        self.created_path = path
        note = (""
                if path.suffix == shortcut_suffix()
                else "\n\nWindows wouldn't let PowerShell write a .lnk, so this "
                     "is a .cmd launcher instead — it double-clicks the same.")
        QMessageBox.information(
            self, "Shortcut created", f"Created {path}{note}")
        self.accept()
