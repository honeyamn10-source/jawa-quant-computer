"""In-process event bus used to stream structured events to SSE subscribers."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from jqc.core.schemas import Event


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: Event) -> None:
        for q in list(self._subscribers):
            if q.full():
                with suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            with suppress(asyncio.QueueFull, RuntimeError):
                q.put_nowait(event)


class EventHistory:
    """Ring buffer so newly-connected SSE clients can catch up."""

    def __init__(self, size: int = 2000) -> None:
        self.size = size
        self._events: list[dict] = []

    def append(self, event: Event) -> None:
        self._events.append(event.model_dump())
        if len(self._events) > self.size:
            del self._events[: len(self._events) - self.size]

    def all(self) -> list[dict]:
        return list(self._events)

    def for_task(self, task_id: str) -> list[dict]:
        return [e for e in self._events if e.get("task_id") == task_id]
