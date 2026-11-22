"""Screenshot flows in each theme, offscreen, for before/after comparisons.

    python scripts/theme_shots.py OUT_DIR [--themes dark,light,...] [FLOW ...]

With no flows, shoots the two the UI redesign checks against: the small
join flow and the large multi-frame one. Each shot is the whole window at
1600x1000, saved as ``<flow>__<theme>.png``.

Nothing real is touched: settings, the user folder and the keychain point at
a throwaway folder, and each flow is copied there before it is opened.
WebEngine cards render blank offscreen; that is the grab, not the app.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "src" / "flograph" / "templates"
DEFAULT_FLOWS = ("04_join_groupby_compare.flograph",
                 "07_retail_ops_command_center.flograph")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("flows", nargs="*", type=Path)
    parser.add_argument("--themes", default="dark,light,dark_slate")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="flograph-shots-"))
    os.environ["FLOGRAPH_USER_DIR"] = str(tmp / "user")
    os.environ["FLOGRAPH_KEYS"] = "file"
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT / "src"))

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    for fmt in (QSettings.NativeFormat, QSettings.IniFormat):
        QSettings.setPath(fmt, QSettings.UserScope, str(tmp / "settings"))

    from flograph.core import NodeRegistry
    from flograph.ui import theme
    from flograph.ui.mainwindow import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    registry = NodeRegistry()
    registry.load_builtins()
    flows = args.flows or [TEMPLATES / name for name in DEFAULT_FLOWS]
    args.out.mkdir(parents=True, exist_ok=True)

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    try:
        for name in args.themes.split(","):
            theme.apply_theme(app, name.strip())
            for flow in flows:
                copy = tmp / Path(flow).name
                shutil.copy(flow, copy)
                window = MainWindow(registry)
                window.confirm_close = False
                window.resize(1600, 1000)
                window.show()
                window.open_path(str(copy), confirm=False)
                pump(3)
                target = args.out / f"{Path(flow).stem}__{name.strip()}.png"
                window.grab().save(str(target))
                print("saved", target)
                window.close()
                window.deleteLater()
                pump(0.3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
