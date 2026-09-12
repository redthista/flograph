"""The `flograph` command — a small subcommand dispatcher.

    flograph                             open the GUI
    flograph path/to/flow.flograph       open the GUI with that project loaded
    flograph run flow.flograph           run the flow to completion, no GUI
    flograph run flow.flograph --var region=North   ... with a Variables override
    flograph --version

`run` is the headless path (see `flograph.engine.headless`): it loads the
file, applies any `--var name=value` overrides, runs the whole graph on a
`QCoreApplication` — no widgets, no display — and exits non-zero if a node
failed. It still needs PySide6 installed, because the engine uses Qt signals
and an event loop; it does not need a screen. Anything that is not a
recognised subcommand or flag opens the GUI, so `flograph` and
`flograph some.flograph` behave exactly as before.
"""
from __future__ import annotations

import sys


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("flograph")
    except PackageNotFoundError:  # a source tree with no install
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    # A crash inside Qt — an abort, a segfault — leaves nothing behind but an
    # exit code, and a coredump too truncated to walk. faulthandler catches
    # those signals and prints the Python stack of every thread to stderr on
    # the way down, which is the difference between a repro hunt and a line
    # number. Only on the CLI path, so imports and tests are untouched.
    # Guarded: it writes to stderr's file descriptor, and a captured stderr
    # (pytest, a pipe a caller has replaced) has none — a diagnostic must
    # never be the reason the program won't start.
    import faulthandler
    try:
        faulthandler.enable()
    except (ValueError, OSError):
        pass

    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] == "run":
        from flograph.engine.headless import main as headless_main
        return headless_main(args[1:])

    if args and args[0] in ("-V", "--version"):
        print(f"flograph {_version()}")
        return 0

    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0

    # Not a subcommand — open the GUI. app.main() reads the real sys.argv
    # itself (Qt wants argv[0] to be the program name), so hand it nothing.
    from flograph.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
