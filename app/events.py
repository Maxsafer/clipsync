from __future__ import annotations

import json
import queue
import threading
import time
from typing import Iterator


class Broker:
    """In-memory pubsub for SSE. One instance per process; safe because the
    container runs gunicorn with a single worker."""

    def __init__(self) -> None:
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def publish(self, event: str, data: dict | list | None) -> None:
        payload = (event, data)
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                # Slow client — drop the event rather than block the publisher.
                pass


def sse_stream(broker: Broker) -> Iterator[bytes]:
    q = broker.subscribe()
    try:
        # Initial ping so the connection is established immediately.
        yield b": connected\n\n"
        last_heartbeat = time.monotonic()
        while True:
            try:
                event, data = q.get(timeout=15)
            except queue.Empty:
                yield b": heartbeat\n\n"
                last_heartbeat = time.monotonic()
                continue
            body = json.dumps(data, default=str)
            frame = f"event: {event}\ndata: {body}\n\n".encode("utf-8")
            yield frame
            if time.monotonic() - last_heartbeat > 30:
                yield b": heartbeat\n\n"
                last_heartbeat = time.monotonic()
    finally:
        broker.unsubscribe(q)
