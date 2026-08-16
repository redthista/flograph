"""Resolving `${name}` at dispatch — the runtime half of `core.varlinks`.

Substitution happens in exactly one place: `scheduler._start_node`, the
single point where a node's params are handed to a worker. Nothing below it
knows a variable existed, which is what keeps the node contract
(`run(ctx, **inputs)` over `ctx.params`) unchanged.

Deliberately *not* substituted into a node's source. A script would then
run text that differs from what the editor shows, and one variable holding a
newline would shift every line number in the file — silently breaking the
`<node:{id}>` virtual-filename mapping that puts a traceback on the right
editor line. Code gets `ctx.vars` instead, which is a real mapping.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from ..core.varlinks import (
    VAR_PORT, VariableError, substitute_params, uses_env,
)


def available(graph, node_id: str, cache) -> dict[str, Any]:
    """Every variable this node can see, merged from the Variables nodes it
    reads.

    The derived edges guarantee those have already run, so their outputs are
    in the cache. Sources are merged in `var_sources` order (sorted by id,
    so it is stable) — but a name reachable from two Variables nodes is
    refused up front by `var_problem`, so no merge here can actually shadow
    anything.
    """
    values: dict[str, Any] = {}
    for src in graph.var_sources(node_id):
        produced = cache.outputs_for(src).get(VAR_PORT)
        if isinstance(produced, Mapping):
            values.update(produced)
    return values


def resolve(graph, node_id: str, cache) -> tuple[dict[str, Any],
                                                 Mapping[str, Any]]:
    """`(params with every ${name} replaced, the variables as a mapping)`.

    Raises VariableError if a reference cannot be resolved. The scheduler
    screens for that before dispatch via `var_problem`, so this is the
    backstop rather than the usual path — but it is a backstop that fails
    the node loudly instead of letting a literal "${region}" reach a filter.
    """
    node = graph.nodes[node_id]
    values = available(graph, node_id, cache)
    env = graph.env if uses_env(node) else None
    params = substitute_params(node, values, env)
    # Read-only structurally, not by promise: nodes run on pool threads, and
    # a shared mutable store there would make a re-run depend on what ran
    # beside it. Variables are something a flow declares, not something a
    # node edits.
    return params, MappingProxyType(dict(values))


def problem(graph, node_id: str, cache) -> str | None:
    """Why this node's references cannot be resolved *right now*, or None.

    Complements the static `varlinks.var_problem`: this one catches the
    runtime half — a Variables node that produced nothing, or a `${env:}`
    key missing from the secrets file, neither of which is visible from the
    params alone.
    """
    try:
        resolve(graph, node_id, cache)
    except VariableError as exc:
        return f"not configured: {exc}"
    return None
