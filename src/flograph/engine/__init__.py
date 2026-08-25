"""flograph.engine — background execution of the node graph.

May import Qt (QObject/QThreadPool/signals) but never widgets; the GUI-thread
boundary is: workers compute, the ExecutionEngine mutates graph and cache.
"""
from .cache import CacheEntry, OutputCache, summarize
from .cache_worker import CacheLoadRunnable, CacheLoadSignals
from .context import CancellationToken, NodeCancelled, RunContext
from .errors import NodeError, build_node_error
from .introspect import upstream_columns
from .scheduler import (ExecutionEngine, RunFlags, build_plan,
                        default_workers, is_exclusive)
from .worker import NodeRunnable, WorkerSignals

__all__ = [
    "CacheEntry", "OutputCache", "summarize",
    "CacheLoadRunnable", "CacheLoadSignals",
    "CancellationToken", "NodeCancelled", "RunContext",
    "NodeError", "build_node_error", "upstream_columns",
    "ExecutionEngine", "RunFlags", "build_plan", "default_workers",
    "is_exclusive",
    "NodeRunnable", "WorkerSignals",
]
