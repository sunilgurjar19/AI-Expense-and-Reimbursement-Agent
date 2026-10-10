"""In-process pub/sub used to stream live updates to browsers over SSE."""

import asyncio
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, user_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers[user_id].add(queue)
        return queue

    def unsubscribe(self, user_id: str, queue: asyncio.Queue) -> None:
        self._subscribers[user_id].discard(queue)
        if not self._subscribers[user_id]:
            self._subscribers.pop(user_id, None)

    def publish(self, user_id: str, event_type: str, data: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(user_id, ())):
            try:
                queue.put_nowait({"type": event_type, "data": data})
            except asyncio.QueueFull:
                logger.warning("Dropping event %s for slow subscriber %s", event_type, user_id)


event_bus = EventBus()
