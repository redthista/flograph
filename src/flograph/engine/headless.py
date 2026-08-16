"""Run a .flograph project without the GUI:

    python -m flograph.engine.headless project.flograph
    python -m flograph.engine.headless project.flograph --var region=North

`--var name=value` overrides what the project's Variables node declares, so
one flow becomes a parameterisable job: the same canvas, run per region or
per date by a scheduler, with nothing edited in between. Repeat the flag for
each variable. A name the flow does not declare is refused rather than
ignored — a typo that silently ran the default would be worse than a stop.

Exit code 0 if every node ran clean, 1 otherwise. Useful for debugging and
for treating a canvas project as a batch script.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication

from flograph.core import NodeRegistry, NodeStatus, serialization
from flograph.core.varlinks import (
    ASSIGNMENTS_PARAM, is_vars, parse_assignments,
)
from flograph.paths import user_nodes_dir

from .scheduler import ExecutionEngine


def parse_args(argv: list[str]) -> tuple[str, dict[str, str]]:
    """`(project path, overrides)`, or ValueError with what was wrong."""
    project = None
    overrides: dict[str, str] = {}
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        if arg == "--var":
            if not rest:
                raise ValueError("--var needs a name=value")
            arg = "--var=" + rest.pop(0)
        if arg.startswith("--var="):
            name, sep, value = arg[len("--var="):].partition("=")
            if not sep or not name.isidentifier():
                raise ValueError(f"expected --var name=value, got {arg!r}")
            overrides[name] = value
            continue
        if arg.startswith("-"):
            raise ValueError(f"unknown option {arg!r}")
        if project is not None:
            raise ValueError("only one project file at a time")
        project = arg
    if project is None:
        raise ValueError("no project file given")
    return project, overrides


def apply_overrides(graph, overrides: dict[str, str]) -> None:
    """Rewrite the Variables nodes' text so the overrides take effect.

    Editing the declaration, rather than injecting values further down, is
    what keeps a --var run identical to opening the project and typing the
    value in: same edges, same fingerprints, same everything.
    """
    if not overrides:
        return
    remaining = dict(overrides)
    for node_id, node in graph.nodes.items():
        if not is_vars(node):
            continue
        declared, _ = parse_assignments(node.params.get(ASSIGNMENTS_PARAM))
        applied = {name: remaining.pop(name) for name in list(remaining)
                   if name in declared}
        if not applied:
            continue
        declared.update(applied)
        graph.set_param(node_id, ASSIGNMENTS_PARAM,
                        "\n".join(f"{k} = {v}" for k, v in declared.items()))
    if remaining:
        names = ", ".join(sorted(remaining))
        raise ValueError(f"no variable named {names} in this project")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    try:
        project, overrides = parse_args(argv)
    except ValueError as exc:
        print(f"{exc}\n\n{__doc__.strip()}", file=sys.stderr)
        return 2

    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    registry = NodeRegistry()
    registry.load_builtins()
    registry.load_user_nodes(user_nodes_dir())
    graph = serialization.load(project, registry)
    try:
        apply_overrides(graph, overrides)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
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
