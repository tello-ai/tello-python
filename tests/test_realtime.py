import pytest

from tello.realtime import EventEmitter


async def test_sync_and_async_handlers_both_fire():
    emitter = EventEmitter()
    seen = []

    @emitter.on("user.turn")
    def sync_handler(event):
        seen.append(("sync", event))

    @emitter.on("user.turn")
    async def async_handler(event):
        seen.append(("async", event))

    await emitter.emit("user.turn", 42)
    assert seen == [("sync", 42), ("async", 42)]


async def test_direct_registration_returns_handler():
    emitter = EventEmitter()

    def handler(event):
        pass

    assert emitter.on("x", handler) is handler


async def test_off_removes_handler():
    emitter = EventEmitter()
    calls = []
    handler = lambda e: calls.append(e)  # noqa: E731
    emitter.on("x", handler)
    emitter.off("x", handler)
    await emitter.emit("x", 1)
    assert calls == []


async def test_emit_unknown_type_is_noop():
    emitter = EventEmitter()
    await emitter.emit("nobody-listening", 1)


async def test_off_missing_handler_is_safe():
    emitter = EventEmitter()
    emitter.off("x", lambda e: None)
