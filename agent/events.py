import asyncio
from typing import Any, Dict, Set

class EventBroker:
    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue):
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(self, event_type: str, data: Dict[str, Any]):
        message = {"type": event_type, "data": data}
        async with self._lock:
            for queue in list(self._subscribers):
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    pass

broker = EventBroker()
