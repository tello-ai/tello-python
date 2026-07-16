"""Tello WebSocket realtime client.

Opens a single WS connection to the turn-provider-gateway ``/sdk`` endpoint,
sends command frames (``create_call`` / ``answer`` / ``cancel``) and dispatches
inbound turn/status/terminal/error events to pub/sub handlers.

Design notes
------------
* Auth is an application-level handshake, not an upgrade header. After the
  socket opens the client sends an ``auth`` frame carrying the API key in its
  ``token`` field as its **first** frame, then blocks until the server replies ``auth.ok``
  before :meth:`connect` returns. The API key never appears on the WS upgrade
  request, in the URL query, in logs, or in any exception message. An
  ``unauthenticated`` error frame, a close with code 4401, or a timeout waiting
  for ``auth.ok`` all fail :meth:`connect` with
  :class:`~tello.errors.AuthenticationError`. This handshake is internal: no
  business command can run until :meth:`connect` has succeeded.
* The gateway keeps the socket **open** on command errors (it never sends a
  terminal frame for a rejected ``create_call``). :meth:`wait_closed` therefore
  resolves on a call-start rejection too, raising the mapped exception, so a
  failed ``create_call`` does not hang the caller.
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

from .commands import (
    answer_frame,
    auth_frame,
    cancel_frame,
    create_call_frame,
    encode,
    get_summary_frame,
    send_dtmf_frame,
    send_sms_frame,
)
from .config import DEFAULT_URL, ENV_API_KEY, ENV_URL, ClientConfig
from .errors import (
    AuthenticationError,
    ConnectionClosedError,
    SessionReplacedError,
    TelloError,
    exception_for,
)
from .events import ErrorEvent, Event, EventType, is_terminal, parse_event
from .realtime import EventEmitter

logger = logging.getLogger("tello")

_CLOSE_UNAUTHENTICATED = 4401
_CLOSE_SESSION_REPLACED = 4429

# Error codes that do NOT abort a pending create_call wait: noActiveCall is
# benign, and callAlreadyActive means an existing call is still running and
# will produce its own terminal event.
_NON_ABORTING_ERROR_CODES = frozenset({"noActiveCall", "callAlreadyActive"})


class TelloClient(EventEmitter):
    """Async pub/sub client for the gateway ``/sdk`` WebSocket.

    Use as an async context manager::

        async with TelloClient(api_key="tello_live_xxx", url="ws://host/sdk") as client:
            @client.on(EventType.USER_TURN)
            async def _(event):
                await client.answer(text="...")
            await client.create_call(to="+821012345678", prompt="...")
            await client.wait_closed()

    ``api_key`` / ``url`` fall back to ``TELLO_API_KEY`` / ``TELLO_URL`` when omitted.
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
        self._call_done = asyncio.Event()  # current call reached a terminal state
        self._closed = asyncio.Event()  # the WS connection has closed
        self._close_exc: TelloError | None = None  # connection-level error to raise
        self._call_error: TelloError | None = None  # call-level error to raise once
        self._active = False  # a call is in progress (awaiting its terminal event)
        self._call_gen = 0  # bumped on each create_call to detect re-entrant calls

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> "TelloClient":
        """Open the WS connection, authenticate, and start the receive loop.

        Authentication is internal: this coroutine only returns once the server
        has confirmed the API key with ``auth.ok``. Any auth failure/timeout
        raises :class:`~tello.errors.AuthenticationError` (or another
        :class:`~tello.errors.TelloError`) and the socket is closed.
        """
        self._call_done.clear()
        self._closed.clear()
        self._close_exc = None
        self._call_error = None
        self._ws = await websockets.connect(
            self._config.url,
            open_timeout=self._config.open_timeout,
            close_timeout=self._config.close_timeout,
        )
        try:
            await self._authenticate()
        except BaseException:
            # Never leave a half-open socket behind on an auth failure.
            try:
                await self._ws.close()
            finally:
                self._ws = None
            raise
        self._recv_task = asyncio.create_task(self._recv_loop())
        return self

    async def _authenticate(self) -> None:
        """Perform the application-level auth handshake before any command.

        Sends the ``auth`` frame (API key in its ``token`` field) as the first
        frame, then blocks until the server returns ``auth.ok``. An
        ``unauthenticated`` error frame, a 4401 close, or a wait timeout are all
        raised as connection failures. The API key is never included in any
        raised message.
        """
        await self._ws.send(encode(auth_frame(self._config.api_key)))
        try:
            raw = await asyncio.wait_for(
                self._ws.recv(), timeout=self._config.open_timeout
            )
        except asyncio.TimeoutError:
            raise AuthenticationError(
                "timed out waiting for authentication acknowledgement"
            ) from None
        except ConnectionClosed as exc:
            raise self._auth_close_error(exc) from None

        try:
            frame = json.loads(raw)
        except (ValueError, TypeError):
            raise AuthenticationError("invalid authentication response") from None
        if not isinstance(frame, dict):
            raise AuthenticationError("invalid authentication response") from None

        if frame.get("type") == "auth.ok":
            return
        if frame.get("type") == "error" and frame.get("code") == "unauthenticated":
            raise AuthenticationError(frame.get("message") or "unauthenticated")
        raise AuthenticationError("unexpected authentication response")

    def _auth_close_error(self, exc: ConnectionClosed) -> TelloError:
        """Map a socket close during the auth handshake to a typed error."""
        received = getattr(exc, "rcvd", None)
        code = received.code if received is not None else getattr(self._ws, "close_code", None)
        if code == _CLOSE_UNAUTHENTICATED:
            return AuthenticationError("unauthenticated")
        if code == _CLOSE_SESSION_REPLACED:
            return SessionReplacedError("session replaced")
        return ConnectionClosedError("connection closed during authentication")

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

        Raises the connection error (auth / session-replaced / abnormal
        mid-call disconnect) or a call-start rejection error if one occurred.
        """
        call_done = asyncio.ensure_future(self._call_done.wait())
        closed = asyncio.ensure_future(self._closed.wait())
        try:
            await asyncio.wait({call_done, closed}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            call_done.cancel()
            closed.cancel()
        if self._close_exc is not None:
            raise self._close_exc
        if self._call_error is not None:
            error = self._call_error
            self._call_error = None
            raise error

    # -- commands ----------------------------------------------------------

    async def create_call(
        self,
        to: str,
        prompt: str = "",
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        """Start a call. Resets terminal state so :meth:`wait_closed` tracks it."""
        self._call_gen += 1
        self._call_done.clear()
        self._call_error = None
        self._active = True
        await self._send(create_call_frame(to, prompt, metadata, request_id))

    async def answer(
        self,
        text: str = "",
        message_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Send the SDK's reply to the current user turn."""
        await self._send(answer_frame(text, message_id, request_id))

    async def send_dtmf(
        self,
        digits: str,
        message_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Send DTMF digits to the current call."""
        await self._send(send_dtmf_frame(digits, message_id, request_id))

    async def cancel(self) -> None:
        """Cancel the active call (no-op server-side if none active)."""
        await self._send(cancel_frame())

    async def get_summary(self, call_id: str, request_id: str | None = None) -> None:
        """Request a completed call summary."""
        await self._send(get_summary_frame(call_id, request_id))

    async def send_sms(
        self,
        to: str,
        message: str,
        request_id: str | None = None,
    ) -> None:
        """Send an SMS through the authenticated account."""
        await self._send(send_sms_frame(to, message, request_id))

    async def _send(self, frame: dict[str, Any]) -> None:
        if self._ws is None:
            raise self._close_exc or ConnectionClosedError("client is not connected")
        try:
            await self._ws.send(encode(frame))
        except ConnectionClosed as exc:
            raise self._connection_error(exc) from exc

    def _connection_error(self, exc: ConnectionClosed | None = None) -> TelloError:
        """Best-effort typed error for a send/close on a dead socket.

        Prefers the error the receive loop already recorded; otherwise derives
        one from the socket close code (covers the connect-then-send race where
        the 4401/4429 close has not been processed by the receive loop yet).
        """
        if self._close_exc is not None:
            return self._close_exc
        code = getattr(self._ws, "close_code", None)
        if code == _CLOSE_UNAUTHENTICATED:
            return AuthenticationError("unauthenticated")
        if code == _CLOSE_SESSION_REPLACED:
            return SessionReplacedError("session replaced")
        return ConnectionClosedError(str(exc) if exc is not None else "connection closed")

    # -- receive loop ------------------------------------------------------

    async def _recv_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    frame = json.loads(raw)
                except (ValueError, TypeError):
                    logger.warning("tello: dropping non-JSON frame")
                    continue
                if not isinstance(frame, dict):
                    logger.warning("tello: dropping non-object frame")
                    continue
                await self._dispatch(frame)
        except ConnectionClosed as exc:
            self._note_close(exc)
        finally:
            await self._finish()

    async def _dispatch(self, frame: dict[str, Any]) -> None:
        event = parse_event(frame)

        if isinstance(event, ErrorEvent):
            exc = exception_for(event.code, event.message, event.question)
            if event.code == "unauthenticated":
                self._close_exc = exc
            elif event.code not in _NON_ABORTING_ERROR_CODES and self._active:
                # The gateway sends no terminal frame for a rejected command, so
                # unblock wait_closed() with the mapped error instead of hanging.
                self._call_error = exc
                self._active = False
                self._call_done.set()
            await self._safe_emit(EventType.ERROR, event)
            return

        # Snapshot the call generation: if a terminal handler starts a follow-up
        # call, _call_gen advances and we must not re-set _call_done for it.
        gen = self._call_gen
        await self._safe_emit(event.type, event)
        if isinstance(event, Event) and is_terminal(event) and self._call_gen == gen:
            self._active = False
            self._call_done.set()

    async def _safe_emit(self, event_type: str, event: Any) -> None:
        try:
            await self.emit(event_type, event)
        except Exception:  # noqa: BLE001 - a bad handler must not kill the loop
            logger.exception("tello: event handler for %r raised", event_type)

    def _note_close(self, exc: ConnectionClosed) -> None:
        if self._close_exc is not None:
            return
        received = getattr(exc, "rcvd", None)
        code = received.code if received is not None else getattr(self._ws, "close_code", None)
        reason = received.reason if received is not None else None
        if code == _CLOSE_UNAUTHENTICATED:
            self._close_exc = AuthenticationError(reason or "unauthenticated")
        elif code == _CLOSE_SESSION_REPLACED:
            self._close_exc = SessionReplacedError(reason or "session replaced")

    async def _finish(self) -> None:
        # A close (clean or abnormal) while a call is still active means the call
        # never reached a terminal event: surface it rather than letting
        # wait_closed() report a phantom success.
        if self._active and self._close_exc is None and self._call_error is None:
            self._close_exc = ConnectionClosedError("connection closed before call terminated")
        # Surface disconnect to subscribers as a typed Event, then unblock any
        # waiter. session_id/call_id/timestamp are empty: this is an SDK-local
        # pseudo-event.
        await self._safe_emit(
            EventType.DISCONNECTED,
            Event(
                type=EventType.DISCONNECTED,
                version="",
                session_id="",
                call_id="",
                timestamp="",
                raw={},
            ),
        )
        self._closed.set()
        self._call_done.set()
