"""Pub/sub event emitter used by :class:`tello.client.TelloClient`.

Handlers may be sync or async and are registered per event ``type``.
"""

from __future__ import annotations

import inspect
from collections import defaultdict
from typing import Any, Callable

Handler = Callable[[Any], Any]


class EventEmitter:
    """Minimal async-aware pub/sub registry keyed by event type string."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def on(self, event_type: str, handler: Handler | None = None):
        """Register ``handler`` for ``event_type``.

        Usable directly (``emitter.on("user.turn", fn)``) or as a decorator
        (``@emitter.on("user.turn")``). Returns the handler either way.
        """
        if handler is None:

            def decorator(fn: Handler) -> Handler:
                self._handlers[event_type].append(fn)
                return fn

            return decorator

        self._handlers[event_type].append(handler)
        return handler

    def off(self, event_type: str, handler: Handler) -> None:
        """Remove a previously registered handler (no-op if absent)."""
        handlers = self._handlers.get(event_type)
        if handlers and handler in handlers:
            handlers.remove(handler)

    async def emit(self, event_type: str, event: Any) -> None:
        """Invoke every handler for ``event_type`` in registration order.

        Awaits any coroutine results. Iterates a snapshot so handlers may
        register/unregister during dispatch.
        """
        for handler in list(self._handlers.get(event_type, ())):
            result = handler(event)
            if inspect.isawaitable(result):
                await result
