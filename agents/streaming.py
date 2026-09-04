"""Thread-local streaming sink for Server-Sent Events.

Agents emit progress events (LLM tokens, list rows) through this module while
they run. The HTTP streaming view installs a :class:`StreamSink` on the current
thread and consumes its queue to produce SSE. When no sink is installed, every
:func:`emit` call is a cheap no-op, so the normal JSON path is unchanged.
"""

from __future__ import annotations

import queue
import threading

_local = threading.local()


class StreamSink:
    """Collects streaming events on a queue; ``None`` is the end sentinel."""

    def __init__(self) -> None:
        self.q: queue.Queue = queue.Queue()

    def emit(self, event: str, data: dict) -> None:
        try:
            self.q.put({"event": event, "data": data})
        except Exception:
            pass

    def finish(self) -> None:
        try:
            self.q.put(None)
        except Exception:
            pass


def get_sink() -> StreamSink | None:
    """Return the active sink for this thread, or ``None``."""
    return getattr(_local, "sink", None)


def set_sink(sink: StreamSink | None) -> None:
    """Install (or clear) the active sink for this thread."""
    _local.sink = sink


def emit(event: str, data: dict) -> None:
    """Emit a streaming event (no-op when no sink is active)."""
    sink = get_sink()
    if sink is not None:
        sink.emit(event, data)
