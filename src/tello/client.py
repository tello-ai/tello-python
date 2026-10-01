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
* The gateway keeps the socket **open** on command errors (contract §6). Only
  the call's own ``create_call`` can fail in a way that ends the call (refused
  before ``call.created``, or its stream failing after it), and then the
  gateway sends no terminal frame, just an error echoing that command's
  ``requestId``. :meth:`create_call` therefore always sends a ``requestId``
  (generated when omitted), and :meth:`wait_closed` raises the mapped
  exception only for an error echoing one of the current call's
  ``create_call`` requestIds. ``noActiveCall`` never ends the call, and
  ``callAlreadyActive`` ends it only when it answers the ``create_call`` that
  started it (contract §4.1). Errors from other commands (``answer`` /
  ``send_dtmf`` / ``get_summary`` / ``cancel``) leave the call running and
  only reach ``ERROR`` handlers.
* Every call keeps its own outcome. A call ends (terminal frame, an error that
  ends it, or the connection closing) before the frame reaches any handler, so
  a wait started during a call reports that call even when a handler has
  already started the next one.
* The gateway drives a WS-level ping heartbeat; the ``websockets`` library
  answers pongs automatically, so no app-level heartbeat is needed here.
* There is no reconnect/resume protocol (gateway does not support it).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any
from urllib.parse import quote, unquote_plus, urlencode, urlsplit, urlunsplit

import websockets
from websockets.exceptions import ConnectionClosed

from ._version import __version__
from .commands import (
    answer_frame,
    auth_frame,
    cancel_frame,
    create_call_frame,
    encode,
    get_summary_frame,
    send_dtmf_frame,
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
from .types import PROTOCOL_VERSION

logger = logging.getLogger("tello")

_CLOSE_UNAUTHENTICATED = 4401
_CLOSE_SESSION_REPLACED = 4429


def _identified_url(url: str) -> str:
    """Append ``sdk``/``version``/``protocol`` to the upgrade URL query.

    The caller's path and query pairs are kept byte-for-byte; only empty pairs
    and pairs whose form-decoded key is an identity key are dropped, so the
    SDK's values win. The server only logs these.
    """
    parts = urlsplit(url)
    ident = {"sdk": "python", "version": __version__, "protocol": PROTOCOL_VERSION}
    kept = [
        pair
        for pair in parts.query.split("&")
        if pair and unquote_plus(pair.split("=", 1)[0]) not in ident
    ]
    kept.append(urlencode(ident, quote_via=quote))
    return urlunsplit(parts._replace(query="&".join(kept)))


class _CallOutcome:
    """How one call ended, shared by every :meth:`TelloClient.wait_closed` bound to it.

    Each call gets its own instance, so a wait keeps reporting the call it was
    started in after a handler has already started the next one.
    """

    __slots__ = ("ended", "error", "raised")

    def __init__(self) -> None:
        self.ended = asyncio.Event()
        self.error: TelloError | None = None  # None: ended with a terminal event
        self.raised = False  # some wait_closed() has already raised ``error``


class TelloClient(EventEmitter):
    """Async pub/sub client for the gateway ``/sdk`` WebSocket.

    Use as an async context manager::

        async with TelloClient(api_key="tello_live_xxx", url="wss://api.telloai.io/sdk") as client:
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
        self._conn_gen = 0  # bumped by connect(); an older receive loop leaves state alone
        self._close_exc: TelloError | None = None  # connection-level error to raise
        self._active = False  # a call is in progress (awaiting its terminal event)
        self._call_gen = 0  # bumped each time create_call starts a new call
        self._call_request_ids: set[str] = set()  # requestIds of the current call's create_calls
        self._opening_request_id: str | None = None  # the create_call that started it
        # The current call's outcome. Until a call starts on this connection it
        # is the outcome the next call will reach, so an early wait follows it.
        self._call_outcome = _CallOutcome()

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> "TelloClient":
        """Open the WS connection, authenticate, and start the receive loop.

        Authentication is internal: this coroutine only returns once the server
        has confirmed the API key with ``auth.ok``. Any auth failure/timeout
        raises :class:`~tello.errors.AuthenticationError` (or another
        :class:`~tello.errors.TelloError`) and the socket is closed.
        """
        # A new connection starts clean. The previous connection's receive loop
        # is stale from here on, so a call it left active could never end: end
        # it now rather than leave its waits hanging.
        self._conn_gen += 1
        gen = self._conn_gen
        if self._active:
            self._end_call(ConnectionClosedError("connection replaced before call terminated"))
        self._call_request_ids.clear()
        self._opening_request_id = None
        if self._call_outcome.ended.is_set():
            self._call_outcome = _CallOutcome()
        self._close_exc = None
        self._ws = await websockets.connect(
            _identified_url(self._config.url),
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
        self._recv_task = asyncio.create_task(self._recv_loop(self._ws, gen))
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

        A wait started during a call returns when that call ends, with that
        call's outcome, even if a handler has already started the next call;
        call this again to follow the next one. It raises the connection error
        (auth / session-replaced / abnormal mid-call disconnect), or the mapped
        error of the error frame that ended the call: one answering the call's
        :meth:`create_call` (a refusal, or a failure after ``call.created``).
        Errors from other commands do not end the call: they only reach
        ``EventType.ERROR`` handlers and this keeps waiting.

        Started with no call in progress, it returns at once with how the last
        call ended (its error is raised only once) or, if no call has ended
        since :meth:`connect`, waits for the next call to end or the connection
        to close.
        """
        outcome = self._call_outcome
        if outcome.ended.is_set():
            if self._close_exc is not None:
                raise self._close_exc
            if outcome.error is not None and not outcome.raised:
                outcome.raised = True
                raise outcome.error
            return
        await outcome.ended.wait()
        if outcome.error is not None:
            outcome.raised = True
            raise outcome.error

    # -- commands ----------------------------------------------------------

    async def create_call(
        self,
        to: str,
        prompt: str = "",
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        """Start a call; :meth:`wait_closed` then follows it until it ends.

        The frame always carries a ``requestId``: ``request_id`` when non-empty,
        otherwise a generated UUID. The gateway echoes it on this command's
        error frame, which is how :meth:`wait_closed` tells an error that ends
        the call from one that answers another command.

        During a live call the gateway refuses another ``create_call`` with
        ``callAlreadyActive`` and the live call goes on, so the new id only
        joins the live call. If the frame cannot be sent, the call it started
        never began: it ends with the send error, which is raised here too.
        """
        if not request_id:
            request_id = str(uuid.uuid4())
        # Encode before touching call state: a frame that cannot be serialized
        # starts no call at all.
        message = encode(create_call_frame(to, prompt, metadata, request_id))
        starts_call = not self._active
        if starts_call:
            self._call_gen += 1
            self._call_request_ids = {request_id}
            self._opening_request_id = request_id
            self._active = True
            if self._call_outcome.ended.is_set():
                self._call_outcome = _CallOutcome()
        else:
            self._call_request_ids.add(request_id)
        gen = self._call_gen
        try:
            await self._send_encoded(message)
        except TelloError as exc:
            # The gateway never got this frame, so the call it started never
            # began. Unless something else already ended that call, end it here.
            if starts_call and self._active and gen == self._call_gen:
                self._end_call(exc)
            raise

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

    async def _send(self, frame: dict[str, Any]) -> None:
        await self._send_encoded(encode(frame))

    async def _send_encoded(self, message: str) -> None:
        if self._ws is None:
            raise self._close_exc or ConnectionClosedError("client is not connected")
        try:
            await self._ws.send(message)
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

    async def _recv_loop(self, ws: Any, gen: int) -> None:
        close: ConnectionClosed | None = None
        try:
            async for raw in ws:
                if gen != self._conn_gen:
                    continue  # connect() has replaced this socket: nothing it says is current
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
            close = exc
        finally:
            await self._finish(gen, close)

    async def _dispatch(self, frame: dict[str, Any]) -> None:
        event = parse_event(frame)

        # A frame that ends the call ends it before any handler sees the frame:
        # waits on that call are released with its outcome, and a handler that
        # calls create_call() starts a new call instead of joining this one.
        if isinstance(event, ErrorEvent):
            exc = exception_for(event.code, event.message, event.question)
            if event.code == "unauthenticated":
                self._close_exc = exc
            elif self._error_ends_call(event):
                self._end_call(exc)
            await self._safe_emit(EventType.ERROR, event)
            return

        if isinstance(event, Event) and is_terminal(event):
            self._end_call(None)
        await self._safe_emit(event.type, event)

    def _error_ends_call(self, event: ErrorEvent) -> bool:
        """Whether an error frame ends the current call.

        Only the call's own create_call can fail it: refused before
        call.created, or its stream failing after it. The gateway then sends
        that one error, echoing the create_call's requestId, and no terminal
        event; errors from other commands leave the call running. noActiveCall
        never ends a call. callAlreadyActive ends it only when it answers the
        create_call that started it: the gateway is still finishing the previous
        call (contract §4.1), so this one never started and can be retried.
        Answering a create_call sent during the live call, it leaves that call
        running.
        """
        if not self._active or event.request_id not in self._call_request_ids:
            return False
        if event.code == "noActiveCall":
            return False
        if event.code == "callAlreadyActive":
            return event.request_id == self._opening_request_id
        return True

    def _end_call(self, error: TelloError | None) -> None:
        """End the current call with ``error`` (``None``: a terminal event).

        Every wait bound to the call returns with that outcome, and the next
        create_call starts a new call.
        """
        self._active = False
        outcome = self._call_outcome
        if not outcome.ended.is_set():
            outcome.error = error
            outcome.ended.set()

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

    async def _finish(self, gen: int, close: ConnectionClosed | None) -> None:
        if gen != self._conn_gen:
            # connect() replaced this connection before its close came in: the
            # close is about a socket the client no longer uses.
            return
        if close is not None:
            self._note_close(close)
        # A close (clean or abnormal) while a call is still active means the call
        # never reached a terminal event: surface it rather than letting
        # wait_closed() report a phantom success.
        if self._active and self._close_exc is None:
            self._close_exc = ConnectionClosedError("connection closed before call terminated")
        # End the call, or release waits for the next one, before DISCONNECTED
        # handlers run. A handler may reconnect, so nothing after the emit may
        # touch client state.
        self._end_call(self._close_exc)
        # Surface disconnect to subscribers as a typed Event. session_id/call_id/
        # timestamp are empty: this is an SDK-local pseudo-event.
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
