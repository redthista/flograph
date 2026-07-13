"""flograph.engine — background execution of the node graph.

May import Qt (QObject/QThreadPool/signals) but never widgets; the GUI-thread
boundary is: workers compute, the ExecutionEngine mutates graph and cache.
"""
from .cache import CacheEntry, OutputCache, summarize
from .context import CancellationToken, NodeCancelled, RunContext
from .errors import NodeError, build_node_error
from .introspect import upstream_columns
from .scheduler import ExecutionEngine, build_plan
from .worker import NodeRunnable, WorkerSignals

__all__ = [
    "CacheEntry", "OutputCache", "summarize",
    "CancellationToken", "NodeCancelled", "RunContext",
    "NodeError", "build_node_error", "upstream_columns",
    "ExecutionEngine", "build_plan",
    "NodeRunnable", "WorkerSignals",
]
