"""Tello WebSocket realtime client.

Opens a single WS connection to the turn-provider-gateway ``/sdk`` endpoint,
sends command frames (``create_call`` / ``answer`` / ``cancel``) and dispatches
inbound turn/status/terminal/error events to pub/sub handlers.

Design notes
------------
* Auth is on the WS upgrade request (``Authorization: Bearer <api_key>``). The
  gateway completes the handshake even on a bad key, then sends an ``error``
  frame and closes with code 4401 — so auth failure surfaces on the receive
  loop and is raised from :meth:`wait_closed` / subsequent commands as
  :class:`~tello.errors.AuthenticationError`.
* The gateway drives a WS-level ping heartbeat; the ``websockets`` library
  answers pongs automatically, so no app-level heartbeat is needed here.
* There is no reconnect/resume protocol (gateway does not support it).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from .commands import answer_frame, cancel_frame, create_call_frame, encode
from .config import DEFAULT_URL, ENV_API_KEY, ENV_URL, ClientConfig
from .errors import AuthenticationError, ConnectionClosedError, TelloError, exception_for
from .events import ErrorEvent, EventType, is_terminal, parse_event
from .realtime import EventEmitter

logger = logging.getLogger("tello")

_CLOSE_UNAUTHENTICATED = 4401


class TelloClient(EventEmitter):
    """Async pub/sub client for the gateway ``/sdk`` WebSocket.

    Use as an async context manager::

        async with TelloClient(api_key="tello_live_xxx", url="ws://host/sdk") as client:
            @client.on(EventType.USER_TURN)
            async def _(event):
                await client.answer(text="...")
            await client.create_call(agent_id="agent-1", prompt="...")
            await client.wait_closed()
    """

    def __init__(
        self,
        api_key: str | None = None,
        url: str | None = None,
        *,
        config: ClientConfig | None = None,
    ) -> None:
        super().__init__()
        if config is None:
            resolved_key = api_key if api_key is not None else os.environ.get(ENV_API_KEY)
            if not resolved_key:
                raise ValueError(
                    f"api_key is required (pass api_key=... or set ${ENV_API_KEY})"
                )
            resolved_url = url or os.environ.get(ENV_URL) or DEFAULT_URL
            config = ClientConfig(api_key=resolved_key, url=resolved_url)
        self._config = config
        self._ws: Any = None
        self._recv_task: asyncio.Task[None] | None = None
        self._done = asyncio.Event()
        self._close_exc: TelloError | None = None

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> "TelloClient":
        """Open the WS connection and start the receive loop."""
        headers = {"Authorization": f"Bearer {self._config.api_key}"}
        self._done.clear()
        self._close_exc = None
        self._ws = await websockets.connect(
            self._config.url,
            additional_headers=headers,
            open_timeout=self._config.open_timeout,
            close_timeout=self._config.close_timeout,
        )
        self._recv_task = asyncio.create_task(self._recv_loop())
        return self

    async def aclose(self) -> None:
        """Close the connection and wait for the receive loop to finish."""
        if self._ws is not None:
            await self._ws.close()
        if self._recv_task is not None:
            await self._recv_task

    async def __aenter__(self) -> "TelloClient":
        return await self.connect()

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def wait_closed(self) -> None:
        """Wait until the current call ends or the connection closes.

        Raises the stored connection error (e.g. auth failure) if one occurred.
        """
        await self._done.wait()
        if self._close_exc is not None:
            raise self._close_exc

    # -- commands ----------------------------------------------------------

    async def create_call(
        self,
        agent_id: str,
        prompt: str = "",
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        """Start a call. Resets terminal state so :meth:`wait_closed` tracks it."""
        self._done.clear()
        await self._send(create_call_frame(agent_id, prompt, metadata, request_id))

    async def answer(
        self,
        text: str = "",
        message_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Send the SDK's reply to the current user turn."""
        await self._send(answer_frame(text, message_id, request_id))

    async def cancel(self) -> None:
        """Cancel the active call (no-op server-side if none active)."""
        await self._send(cancel_frame())

    async def _send(self, frame: dict[str, Any]) -> None:
        if self._ws is None:
            raise self._close_exc or ConnectionClosedError("client is not connected")
        try:
            await self._ws.send(encode(frame))
        except ConnectionClosed as exc:
            raise self._close_exc or ConnectionClosedError(str(exc)) from exc

    # -- receive loop ------------------------------------------------------

    async def _recv_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    frame = json.loads(raw)
                except (ValueError, TypeError):
                    logger.warning("tello: dropping non-JSON frame")
                    continue
                await self._dispatch(frame)
        except ConnectionClosed as exc:
            self._note_close(exc)
        finally:
            await self._finish()

    async def _dispatch(self, frame: dict[str, Any]) -> None:
        event = parse_event(frame)

        if isinstance(event, ErrorEvent):
            if event.code == "unauthenticated":
                self._close_exc = exception_for(event.code, event.message, event.question)
            await self._safe_emit(EventType.ERROR, event)
            return

        await self._safe_emit(event.type, event)
        if is_terminal(event):
            self._done.set()

    async def _safe_emit(self, event_type: str, event: Any) -> None:
        try:
            await self.emit(event_type, event)
        except Exception:  # noqa: BLE001 - a bad handler must not kill the loop
            logger.exception("tello: event handler for %r raised", event_type)

    def _note_close(self, exc: ConnectionClosed) -> None:
        received = getattr(exc, "rcvd", None)
        if received is not None and received.code == _CLOSE_UNAUTHENTICATED and self._close_exc is None:
            self._close_exc = AuthenticationError(received.reason or "unauthenticated")

    async def _finish(self) -> None:
        # Surface disconnect to subscribers, then unblock wait_closed().
        await self._safe_emit(EventType.DISCONNECTED, {"type": EventType.DISCONNECTED})
        self._done.set()
