"""Node type registry.

Builtin nodes live as .py files under flograph/nodes/<category_pkg>/ and are
loaded as *text* (never imported as modules) so they go through the same
script contract as user code. type_id = "flograph.<subpackage>.<stem>".
"""
from __future__ import annotations

import importlib.resources
from typing import Optional

from .node import NodeInstance, NodeSpec
from .script import parse_spec


class NodeRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, NodeSpec] = {}

    def register(self, spec: NodeSpec) -> None:
        self._specs[spec.type_id] = spec

    def get(self, type_id: str) -> NodeSpec:
        try:
            return self._specs[type_id]
        except KeyError:
            raise KeyError(
                f"unknown node type {type_id!r} — not in the registry"
            ) from None

    def maybe_get(self, type_id: str) -> Optional[NodeSpec]:
        return self._specs.get(type_id)

    def all(self) -> list[NodeSpec]:
        return sorted(self._specs.values(), key=lambda s: (s.category, s.label))

    def categories(self) -> dict[str, list[NodeSpec]]:
        result: dict[str, list[NodeSpec]] = {}
        for spec in self.all():
            result.setdefault(spec.category, []).append(spec)
        return result

    def instantiate(self, type_id: str, pos: tuple[float, float] = (0.0, 0.0)) -> NodeInstance:
        return NodeInstance.create(self.get(type_id), pos=pos)

    def load_builtins(self) -> list[str]:
        """Scan flograph.nodes subpackages for node scripts. Returns loaded
        type_ids. A malformed builtin raises immediately — shipped nodes must
        always satisfy the contract."""
        loaded: list[str] = []
        root = importlib.resources.files("flograph.nodes")
        for pkg in sorted(root.iterdir(), key=lambda e: e.name):
            if not pkg.is_dir() or pkg.name.startswith(("_", ".")):
                continue
            for entry in sorted(pkg.iterdir(), key=lambda e: e.name):
                if not entry.name.endswith(".py") or entry.name.startswith("_"):
                    continue
                type_id = f"flograph.{pkg.name}.{entry.name[:-3]}"
                self.register(parse_spec(entry.read_text(), type_id, builtin=True))
                loaded.append(type_id)
        return loaded

    def search(self, query: str) -> list[NodeSpec]:
        """Fuzzy search over labels (and, weaker, categories) for the palette."""
        specs = self.all()
        if not query.strip():
            return specs
        scored = []
        for spec in specs:
            score = max(
                fuzzy_score(query, spec.label),
                fuzzy_score(query, spec.category) * 0.5,
            )
            if score > 0:
                scored.append((score, spec))
        scored.sort(key=lambda pair: (-pair[0], pair[1].label))
        return [spec for _, spec in scored]


def fuzzy_score(query: str, text: str) -> float:
    """Subsequence match score: 0 if query is not a subsequence of text.

    Considers every possible alignment (memoized) so "fr" matches the 'R' of
    "Filter Rows" at its word start rather than greedily taking "filte(r)".
    Rewards word-start matches and adjacent runs, penalizes gaps and long
    targets.
    """
    query = query.lower()
    text_lower = text.lower()
    if not query:
        return 0.0

    from functools import lru_cache

    @lru_cache(maxsize=None)
    def best(qi: int, ti: int, prev: int) -> float:
        if qi == len(query):
            return 0.0
        best_score = float("-inf")
        for pos in range(ti, len(text_lower)):
            if text_lower[pos] != query[qi]:
                continue
            at_word_start = pos == 0 or text_lower[pos - 1] in " _-."
            char_score = 4.0 if at_word_start else 1.0
            if pos == prev + 1:
                char_score += 1.5  # adjacency bonus
            char_score -= (pos - ti) * 0.05  # gap penalty
            rest = best(qi + 1, pos + 1, pos)
            if rest != float("-inf"):
                best_score = max(best_score, char_score + rest)
        return best_score

    score = best(0, 0, -2)
    if score == float("-inf"):
        return 0.0
    return max(score, 0.1) / (1.0 + len(text) * 0.01)
