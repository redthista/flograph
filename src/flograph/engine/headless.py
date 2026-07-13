"""Run a .flograph project without the GUI:

    python -m flograph.engine.headless project.flograph

Exit code 0 if every node ran clean, 1 otherwise. Useful for debugging and
for treating a canvas project as a batch script.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication

from flograph.core import NodeRegistry, NodeStatus, serialization
from flograph.paths import user_nodes_dir

from .scheduler import ExecutionEngine


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    registry = NodeRegistry()
    registry.load_builtins()
    registry.load_user_nodes(user_nodes_dir())
    graph = serialization.load(argv[0], registry)
    engine = ExecutionEngine(graph)

    engine.node_log.connect(
        lambda nid, line, stream:
        print(f"[{graph.nodes[nid].label}] {line}",
              file=sys.stderr if stream == "stderr" else sys.stdout)
    )
    engine.node_failed.connect(
        lambda nid, err:
        print(f"[{graph.nodes[nid].label}] FAILED: {err.message}", file=sys.stderr)
    )

    result: dict[str, bool] = {}

    def on_finished(ok: bool) -> None:
        result["ok"] = ok
        app.quit()

    engine.run_finished.connect(on_finished)
    engine.run_all()
    if "ok" not in result:  # nothing to run counts as success
        if not engine.active:
            result["ok"] = True
        else:
            app.exec()

    done = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.DONE)
    print(f"{done}/{len(graph.nodes)} nodes completed", file=sys.stderr)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
