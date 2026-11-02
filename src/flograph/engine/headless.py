"""Run a .flograph project without the GUI:

    flograph run project.flograph
    flograph run project.flograph --var region=North
    python -m flograph.engine.headless project.flograph   # same thing, longhand

The internal ``--capture-output NAME --capture-file PATH`` options return
the value from the named Flow Output node to a Run Flow parent node. They
use a current saved result when available; ``--always-run`` bypasses it.

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
    ASSIGNMENTS_PARAM, BINDABLE, coerce_bound, is_vars, parse_assignments,
    published_name,
)
from flograph.paths import user_data_dir, user_nodes_dir

from .scheduler import ExecutionEngine


def parse_args(
        argv: list[str]
        ) -> tuple[str, dict[str, str], str | None, str | None, bool]:
    """`(project, vars, output name, output file, always run) or ValueError."""
    project = None
    overrides: dict[str, str] = {}
    output_name = output_file = None
    always_run = False
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
        if arg in ("--capture-output", "--capture-file"):
            if not rest:
                raise ValueError(f"{arg} needs a value")
            value = rest.pop(0)
            if not value or value.startswith("-"):
                raise ValueError(f"{arg} needs a value")
            if arg == "--capture-output":
                output_name = value
            else:
                output_file = value
            continue
        if arg.startswith("--capture-output="):
            output_name = arg.partition("=")[2]
            if not output_name:
                raise ValueError("--capture-output needs a value")
            continue
        if arg.startswith("--capture-file="):
            output_file = arg.partition("=")[2]
            if not output_file:
                raise ValueError("--capture-file needs a value")
            continue
        if arg == "--always-run":
            always_run = True
            continue
        if arg.startswith("-"):
            raise ValueError(f"unknown option {arg!r}")
        if project is not None:
            raise ValueError("only one project file at a time")
        project = arg
    if project is None:
        raise ValueError("no project file given")
    if (output_name is None) != (output_file is None):
        raise ValueError("--capture-output and --capture-file must be used together")
    if always_run and output_name is None:
        raise ValueError("--always-run requires output capture")
    return project, overrides, output_name, output_file, always_run


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
    # A named input control is set the way moving it would set it: its
    # value param, in that param's own type — and any held change is
    # dropped, since a command line has no Apply button to press.
    for node_id, node in graph.nodes.items():
        name = published_name(node)
        if not name or name not in remaining or len(node.spec.outputs) != 1:
            continue
        spec = node.spec.param("value")
        raw = remaining.pop(name)
        value = coerce_bound(spec, raw) if spec.type in BINDABLE else raw
        graph.set_param(node_id, "value", value)
        if node.params.get("draft"):
            graph.set_param(node_id, "draft", "")
    if remaining:
        names = ", ".join(sorted(remaining))
        raise ValueError(f"no variable named {names} in this project")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__.strip())
        print("\nInternal output capture: --capture-output NAME --capture-file PATH"
              " [--always-run]")
        return 0
    try:
        project, overrides, output_name, output_file, always_run = parse_args(argv)
    except ValueError as exc:
        print(f"{exc}\n\n{__doc__.strip()}", file=sys.stderr)
        return 2

    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    registry = NodeRegistry()
    registry.load_builtins()
    registry.load_user_nodes(user_nodes_dir())
    registry.load_installed_packs(user_data_dir())
    graph = serialization.load(project, registry)
    for line in graph.dropped_connections:
        print(f"wire left off, it no longer fits its nodes: {line}",
              file=sys.stderr)
    try:
        apply_overrides(graph, overrides)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    output_node_id = None
    if output_name is not None:
        matches = [node_id for node_id, node in graph.nodes.items()
                   if node.type_id == "flograph.scripting.flow_output"
                   and str(node.params.get("name", "")).strip() == output_name]
        if len(matches) != 1:
            reason = "was not found" if not matches else "is ambiguous"
            print(f"flow output {output_name!r} {reason}", file=sys.stderr)
            return 1
        output_node_id = matches[0]
        if not always_run:
            from .cache_persistence import load_cached_outputs
            cached = load_cached_outputs(graph, project, output_node_id)
            if cached is not None and "value" in cached:
                try:
                    from .cache_persistence import _dump
                    with open(output_file, "wb") as stream:
                        _dump(cached["value"], stream)
                except Exception as exc:
                    print(f"couldn't capture cached flow output: {exc}",
                          file=sys.stderr)
                    return 1
                print(f"using saved output {output_name!r}", file=sys.stderr)
                return 0
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
    if not result.get("ok"):
        return 1
    if output_node_id is not None:
        try:
            outputs = engine.cache.outputs_for(output_node_id)
            if "value" not in outputs:
                raise ValueError("the Flow Output node produced no value")
            from .cache_persistence import _dump
            with open(output_file, "wb") as stream:
                _dump(outputs["value"], stream)
        except Exception as exc:
            print(f"couldn't capture flow output {output_name!r}: {exc}",
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
