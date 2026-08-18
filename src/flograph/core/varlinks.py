"""Flow-level variables — `${name}` in a param, and the derived edges that
make the engine see it.

A Variables node names values; any node may then write `${name}` into a text
param and get that value at run time. The reference is the whole user-facing
mechanism, but on its own it would be invisible to the engine, and that is
where every naive implementation of this feature goes wrong: the consumer
would not re-run when the value changed, its cached output would be reused
against a different value, and nothing would guarantee the Variables node
ran first.

So a reference is not a lookup. It is an **edge** — derived exactly the way
`core.links` derives Goto/From links, from node params alone, unioned into
`Graph._iter_edges()` and therefore into `successors`, `topo_order`,
`mark_dirty` and the cache fingerprint. Run ordering, invalidation and loop
rejection all come from machinery that already exists.

The one difference from a Goto/From link: a variable edge carries no value
to a port, so it has an empty `dst_port` and Graph deliberately keeps it out
of the by-input index. It exists to say "this node depends on that one",
nothing more; the values themselves are read from the Variables node's
cached output at dispatch (see `engine.varsubst`).

`${env:NAME}` is a different animal: it resolves from a .env file, not from
a node, so it creates no edge. See `core.dotenv`.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .graph import Connection, Graph

VAR_CARD = "vars"           # NODE["card"] marking a Variables node
NOTE_CARD = "note"          # ...and a Note, which runs nothing — see below
VAR_PORT = "vars"           # the output port its dict arrives on
ASSIGNMENTS_PARAM = "assignments"
ENV_PREFIX = "env:"

# Param types a `${name}` can be typed into. The typed widgets are left out
# on purpose: a QSpinBox cannot hold "${x}", so binding those needs an
# affordance of its own rather than a placeholder in the text.
SUBSTITUTABLE = frozenset({
    "string", "text", "columns", "file_open", "file_save", "folder_open",
    "password",
})

# Deliberately strict — no whitespace, no dotted paths, no expressions. A
# reference is a name or it is literal text, and there is no third reading
# for someone to get wrong. `${...}` is not valid Python or pandas syntax
# anywhere, so this can never collide with `df[['a','b']]` sitting in an
# Expression or Python Script param.
PATTERN = re.compile(r"\$\{(env:)?([A-Za-z_][A-Za-z0-9_]*)\}")

MARKER = "${"               # cheap pre-test before running the regex


class VariableError(Exception):
    """A `${name}` that cannot be resolved. Fails the node that used it."""


def is_vars(node) -> bool:
    return node.spec.card == VAR_CARD


def link_id(consumer_id: str, source_id: str) -> str:
    """A consumer may read from more than one Variables node, so the pair
    names the edge — unlike a From, which has exactly one source."""
    return f"var:{consumer_id}:{source_id}"


# ------------------------------------------------------------- declarations

def parse_assignments(text: Any) -> tuple[dict[str, str], list[str]]:
    """`name = value` per line -> (values, problems).

    The same idiom as the Expression node's assignments, so it reads as this
    app's house style rather than a second one. Blank lines and `#` comments
    are skipped; everything on the right of the first `=` is the value,
    stripped, so a path or a query with an `=` in it survives.

    Problems are returned rather than raised because this runs on every
    keystroke's worth of committed text: a half-typed line must not take the
    panel down, but it must not silently vanish either — the node reports
    them, and `var_problem` puts them on the card.
    """
    values: dict[str, str] = {}
    problems: list[str] = []
    for number, line in enumerate(str(text or "").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep:
            problems.append(f"line {number}: expected 'name = value'")
            continue
        if not name.isidentifier():
            problems.append(f"line {number}: {name!r} is not a valid name")
            continue
        if name in values:
            problems.append(f"line {number}: {name!r} is defined twice")
            continue
        values[name] = value.strip()
    return values, problems


def declared_names(node) -> list[str]:
    """The names a Variables node offers *statically* — from its text alone.

    Wired inputs can add more at run time, but those cannot be known here,
    and a name that only exists after the node runs cannot be turned into an
    edge before the run. Consuming one is an error rather than a feature
    (see the node's docstring): the alternative is a consumer scheduled
    before the value it needs exists.
    """
    return list(parse_assignments(node.params.get(ASSIGNMENTS_PARAM))[0])


# -------------------------------------------------------------- references

def _param_texts(node):
    """Every substitutable param value on a node, as text. See
    `substitutable` for which params qualify."""
    for spec in node.spec.params:
        if not substitutable(node, spec):
            continue
        value = node.params.get(spec.name)
        if isinstance(value, str) and MARKER in value:
            yield spec.name, value


def references(node) -> set[str]:
    """Every `${...}` token on a node, `env:` prefix kept."""
    found: set[str] = set()
    for _name, text in _param_texts(node):
        for env, name in PATTERN.findall(text):
            found.add(f"{ENV_PREFIX}{name}" if env else name)
    return found


def var_references(node) -> set[str]:
    """The references that come from a Variables node."""
    return {r for r in references(node) if not r.startswith(ENV_PREFIX)}


def env_references(node) -> set[str]:
    """The referenced .env keys, without the `env:` prefix."""
    return {r[len(ENV_PREFIX):] for r in references(node)
            if r.startswith(ENV_PREFIX)}


def uses_env(node) -> bool:
    return any(r.startswith(ENV_PREFIX) for r in references(node))


# ----------------------------------------------------------- substitution

def substitute(text: str, values: dict[str, Any],
               env: Optional[dict[str, str]] = None) -> str:
    """Replace every `${name}` in `text`, or raise VariableError.

    Raising rather than leaving the token in place is the same call `From`
    makes when its Goto is missing: a dashboard that quietly reads a literal
    "${region}" as a filter value is worse than one that stops and says why.
    """
    def replace(match: re.Match) -> str:
        name = match.group(2)
        if match.group(1):
            if env is None or name not in env:
                raise VariableError(f"no secret named {name!r} in the .env file")
            return str(env[name])
        if name not in values:
            raise VariableError(f"no variable named {name!r}")
        return str(values[name])

    return PATTERN.sub(replace, text)


def substitute_params(node, values: dict[str, Any],
                      env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """A node's params with every reference resolved. Non-text params, and
    text params with no `${`, are passed through untouched."""
    params = dict(node.params)
    for name, text in _param_texts(node):
        params[name] = substitute(text, values, env)
    return params


# ------------------------------------------------------------- derivation

def providers(graph: "Graph") -> dict[str, list[str]]:
    """name -> the ids of the Variables nodes declaring it.

    A list, not an id: two nodes declaring the same name is a conflict this
    has to be able to *describe*, and refusing to answer at all would leave
    `var_problem` with nothing to say.
    """
    found: dict[str, list[str]] = {}
    for node_id, node in graph.nodes.items():
        if not is_vars(node):
            continue
        for name in declared_names(node):
            found.setdefault(name, []).append(node_id)
    return found


def declared_values(graph: "Graph") -> dict[str, str]:
    """Every variable's *declared* value, across all Variables nodes."""
    values: dict[str, str] = {}
    for node in graph.nodes.values():
        if is_vars(node):
            values.update(parse_assignments(node.params.get(ASSIGNMENTS_PARAM))[0])
    return values


def completion_names(graph: "Graph") -> list[str]:
    """What `${` can be completed to: every declared variable, then every
    key the secrets *file* declares as `env:NAME`.

    Deliberately `graph.env_keys` and not `graph.env` — the latter carries
    the whole process environment as a resolution fallback, and offering
    PATH and HOME in this list would bury the handful of names that matter.
    """
    return (sorted(declared_values(graph))
            + [f"{ENV_PREFIX}{key}" for key in sorted(graph.env_keys or ())])


def substitutable(node, spec) -> bool:
    """Can this param hold a `${name}`? The one place the rule lives — the
    resolver, the panel's marker and its completer all ask here.

    A Variables node's own assignments are excluded: resolving a variable
    out of the text that *defines* variables is a chain nobody asked for,
    and it would make `declared_names` depend on a run.

    A Note's text is excluded because a Note takes no part in execution —
    it has no ports and its `run` returns nothing, and the canvas draws the
    text exactly as written. So substituting into it changes nothing anyone
    can see, while costing two things that are real: a derived edge onto a
    card that consumes nothing, and a *failed run* the moment the text
    names something undeclared. Which is precisely what writing a note
    explaining the `${name}` syntax does — the one note every flow that
    uses variables wants.
    """
    if is_vars(node) and spec.name == ASSIGNMENTS_PARAM:
        return False
    if node.spec.card == NOTE_CARD:
        return False
    return spec.type in SUBSTITUTABLE


def describe(graph: "Graph", node) -> list[str]:
    """One line per reference on a node, for a tooltip: what it resolves to.

    Declared values only — a wired input can override one at run time, and
    this is asked before any run. A secret's value is never included, only
    whether the file has it: this text ends up on screen next to a param.
    """
    values = declared_values(graph)
    lines = []
    for ref in sorted(references(node)):
        if ref.startswith(ENV_PREFIX):
            key = ref[len(ENV_PREFIX):]
            state = ("set in the secrets file" if key in (graph.env or {})
                     else "missing from the secrets file")
            lines.append(f"${{{ref}}} — {state}")
        elif ref in values:
            lines.append(f"${{{ref}}} = {values[ref]}")
        else:
            lines.append(f"${{{ref}}} — not defined by any Variables node")
    return lines


def resolve_var_links(graph: "Graph") -> dict[str, "Connection"]:
    """The full variable-edge set for a graph, keyed by edge id.

    Rebuilt whole for the same reason `links.resolve_links` is: a consumer
    may be added before the Variables node it reads, so there is no correct
    incremental version. Candidates are tested against the real wires *plus*
    the Goto/From links *plus* the variable edges accepted so far, which is
    what catches a loop that no single edge closes on its own.

    An unresolvable reference is simply absent here — no edge, and the node
    still runs unless something asks. `var_problem` is what explains it, and
    the scheduler asks before dispatch.
    """
    from .graph import Connection  # local import: graph imports this module

    by_name = providers(graph)
    if not by_name:
        return {}

    adjacency: dict[str, set[str]] = {}
    for conn in (*graph.connections.values(), *graph.links.values()):
        adjacency.setdefault(conn.src_node, set()).add(conn.dst_node)

    edges: dict[str, "Connection"] = {}
    for node_id, node in graph.nodes.items():
        wanted = var_references(node)
        if not wanted:
            continue
        for name in sorted(wanted):
            sources = by_name.get(name, ())
            if len(sources) != 1:
                continue            # missing, or ambiguous: var_problem says so
            src = sources[0]
            if src == node_id or _reaches(adjacency, node_id, src):
                continue            # the Variables node already depends on us
            key = link_id(node_id, src)
            if key in edges:
                continue            # two names from the same node: one edge
            edges[key] = Connection(
                id=key, src_node=src, src_port=VAR_PORT,
                dst_node=node_id, dst_port="",
            )
            adjacency.setdefault(src, set()).add(node_id)
    return edges


def var_problem(graph: "Graph", node_id: str) -> Optional[str]:
    """Why this node cannot run its `${...}` references, phrased for the
    user — or None if it is fine.

    The scheduler asks before dispatch, so an unresolvable reference stops
    the node instead of reaching a run that would fail with something less
    helpful.
    """
    node = graph.nodes.get(node_id)
    if node is None:
        return None
    if is_vars(node):
        problems = parse_assignments(node.params.get(ASSIGNMENTS_PARAM))[1]
        if problems:
            return f"not configured: {problems[0]}"
    wanted = var_references(node)
    if not wanted:
        return None
    by_name = providers(graph)
    for name in sorted(wanted):
        sources = by_name.get(name, ())
        if not sources:
            return f"not configured: no variable named {name!r}"
        if len(sources) > 1:
            labels = ", ".join(sorted(graph.nodes[s].label for s in sources))
            return (f"not configured: {name!r} is defined by more than one "
                    f"Variables node ({labels})")
        if link_id(node_id, sources[0]) not in graph.var_links:
            return (f"not configured: reading {name!r} here would create "
                    f"a loop")
    return None


def _reaches(adjacency: dict[str, set[str]], start: str, target: str) -> bool:
    """Is `target` downstream of `start` in the given edge set?"""
    seen: set[str] = set()
    stack = [start]
    while stack:
        for nxt in adjacency.get(stack.pop(), ()):
            if nxt == target:
                return True
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False
