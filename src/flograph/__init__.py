"""flograph — a visual node-based Python programming environment.

`flograph.run(path)` runs a `.flograph` project to completion without a GUI,
the library equivalent of `flograph run path` on the command line. Everything
Qt lives behind lazy imports, so `import flograph` stays cheap and Qt-free.
"""
from __future__ import annotations

import os
from typing import Mapping

__all__ = ["run"]


def run(path: str | os.PathLike[str], *,
        variables: Mapping[str, str] | None = None) -> None:
    """Run the `.flograph` project at `path` to completion, headless.

    `variables` overrides what the project's Variables node declares — the
    same as `--var name=value` on `flograph run` — and a name the flow does
    not declare is an error, not a no-op. Raises `RuntimeError` if any node
    fails; returns `None` on success.

    Needs PySide6 installed (the engine runs on a Qt event loop) but no
    display. Output from the nodes goes to stdout/stderr as it does on the
    command line.
    """
    from flograph.engine.headless import main as _headless_main

    argv = [os.fspath(path)]
    for name, value in (variables or {}).items():
        argv += ["--var", f"{name}={value}"]

    code = _headless_main(argv)
    if code != 0:
        raise RuntimeError(
            f"flograph run failed for {os.fspath(path)!r} (exit code {code})")
