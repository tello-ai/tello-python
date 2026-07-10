"""Integration tests driving TelloClient against an in-memory fake gateway.

The fake mimics turn-provider-gateway `/sdk`: Bearer auth on the upgrade
request, inbound `{event, data}` command frames, and flat outbound event frames.
"""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
import websockets

from tello import (
    AuthenticationError,
    ConnectionClosedError,
    EventType,
    SessionReplacedError,
    TelloClient,
    ValidationError,
)

RAW_KEY = "sdk-secret"


def _status_changed(status, previous):
    return json.dumps(
        {
            "type": "call.statusChanged",
            "version": "1.0",
            "sessionId": "session-1",
            "callId": "call-1",
            "status": status,
            "previousStatus": previous,
            "timestamp": "2026-07-01T00:00:00.000Z",
        }
    )


def _user_turn(index, text):
    return json.dumps(
        {
            "type": "user.turn",
            "version": "1.0",
            "sessionId": "session-1",
            "callId": "call-1",
            "turnIndex": index,
            "text": text,
            "timestamp": "2026-07-01T00:00:01.000Z",
        }
    )


def _agent_turn(index, text):
    return json.dumps(
        {
            "type": "agent.turn",
            "version": "1.0",
            "sessionId": "session-1",
            "callId": "call-1",
            "turnIndex": index,
            "text": text,
            "timestamp": "2026-07-01T00:00:01.500Z",
        }
    )


def _completed():
    return json.dumps(
        {
            "type": "call.completed",
            "version": "1.0",
            "sessionId": "session-1",
            "callId": "call-1",
            "status": "completed",
            "timestamp": "2026-07-01T00:00:02.000Z",
        }
    )


def _error(code, message, request_id=None):
    frame = {"type": "error", "version": "1.0", "code": code, "message": message}
    if request_id is not None:
        frame["requestId"] = request_id
    return json.dumps(frame)


def make_gateway(
    auto_complete=True,
    ping_on_create=False,
    drop_after_user_turn=False,
    scalar_frame=False,
    close_4429=False,
):
    async def handler(ws):
        if ws.request.headers.get("Authorization") != f"Bearer {RAW_KEY}":
            await ws.send(_error("unauthenticated", "Authentication required"))
            await ws.close(4401, "unauthenticated")
            return

        active = False
        async for raw in ws:
            msg = json.loads(raw)
            event = msg.get("event")
            data = msg.get("data", {})

            if event == "createCall":
                if not data.get("to"):
                    # rejected create: send error, keep socket open, no terminal
                    await ws.send(_error("toRequired", "to is required", data.get("requestId")))
                    continue
                if not data.get("agentId"):
                    # rejected create: send error, keep socket open, no terminal
                    await ws.send(_error("agentIdRequired", "agentId is required", data.get("requestId")))
                    continue
                if close_4429:
                    await ws.close(4429, "session replaced")
                    return
                active = True
                await ws.send(_status_changed("inProgress", "queued"))
                if scalar_frame:
                    await ws.send(json.dumps(123))  # valid JSON, non-object
                await ws.send(_user_turn(1, "Need help"))
                if drop_after_user_turn:
                    await ws.close()  # abnormal: close mid-call, no terminal
                    return
                if ping_on_create:
                    pong_waiter = await ws.ping()
                    await asyncio.wait_for(pong_waiter, timeout=1)
                if auto_complete:
                    await ws.send(_completed())
                    active = False
            elif event == "answer":
                if not active:
                    await ws.send(_error("noActiveCall", "No active call", data.get("requestId")))
                    continue
                await ws.send(_agent_turn(2, data.get("text", "")))
            elif event == "sendDtmf":
                if not active:
                    await ws.send(_error("noActiveCall", "No active call", data.get("requestId")))
                    continue
                await ws.send(_agent_turn(2, data.get("digits", "")))
            elif event == "cancel":
                await ws.send(_completed())
                active = False

    return handler


@asynccontextmanager
async def running(handler):
    async with websockets.serve(handler, "localhost", 0) as server:
        port = list(server.sockets)[0].getsockname()[1]
        yield f"ws://localhost:{port}/sdk"


async def test_happy_path_streams_contract_order():
    seen = []
    async with running(make_gateway(auto_complete=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            for et in (
                EventType.CALL_STATUS_CHANGED,
                EventType.USER_TURN,
                EventType.CALL_COMPLETED,
            ):
                client.on(et, lambda e: seen.append(e.type))
            await client.create_call(to="+821012345678", agent_id="agent-1", prompt="call the clinic")
            await client.wait_closed()

    assert seen == ["call.statusChanged", "user.turn", "call.completed"]


async def test_user_turn_fields():
    got = {}
    async with running(make_gateway(auto_complete=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:

            @client.on(EventType.USER_TURN)
            def _(event):
                got["index"] = event.turn_index
                got["text"] = event.text
                got["call_id"] = event.call_id

            await client.create_call(to="+821012345678", agent_id="agent-1")
            await client.wait_closed()

    assert got == {"index": 1, "text": "Need help", "call_id": "call-1"}


async def test_answer_produces_agent_turn():
    turns = []
    async with running(make_gateway(auto_complete=False)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:

            @client.on(EventType.AGENT_TURN)
            def _(event):
                turns.append((event.turn_index, event.text))

            await client.create_call(to="+821012345678", agent_id="agent-1")
            await asyncio.sleep(0.05)  # let user.turn arrive
            await client.answer(text="The 2 PM slot is open.")
            await asyncio.sleep(0.05)
            await client.cancel()
            await client.wait_closed()

    assert turns == [(2, "The 2 PM slot is open.")]


async def test_send_dtmf_produces_agent_turn():
    turns = []
    async with running(make_gateway(auto_complete=False)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:

            @client.on(EventType.AGENT_TURN)
            def _(event):
                turns.append((event.turn_index, event.text))

            await client.create_call(to="+821012345678", agent_id="agent-1")
            await asyncio.sleep(0.05)  # let user.turn arrive
            await client.send_dtmf(digits="1234#")
            await asyncio.sleep(0.05)
            await client.cancel()
            await client.wait_closed()

    assert turns == [(2, "1234#")]


async def test_error_frame_echoes_request_id():
    errors = []
    async with running(make_gateway(auto_complete=False)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:

            @client.on(EventType.ERROR)
            def _(event):
                errors.append((event.code, event.request_id))

            # answer with no active call -> noActiveCall error, requestId echoed
            await client.answer(text="hi", request_id="req-1")
            await asyncio.sleep(0.05)

    assert errors == [("noActiveCall", "req-1")]


async def test_unauthenticated_raises_from_wait_closed():
    async with running(make_gateway()) as url:
        client = TelloClient(api_key="wrong-key", url=url)
        await client.connect()
        with pytest.raises(AuthenticationError):
            await client.wait_closed()
        await client.aclose()


async def test_rejected_create_unblocks_wait_closed():
    # gateway rejects create_call (empty agentId) with an error frame and no
    # terminal/close; wait_closed() must raise, not hang.
    async with running(make_gateway(auto_complete=False)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            await client.create_call(to="+821012345678", agent_id="")
            with pytest.raises(ValidationError):
                await asyncio.wait_for(client.wait_closed(), timeout=2)


async def test_rejected_create_missing_to_unblocks_wait_closed():
    async with running(make_gateway(auto_complete=False)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            await client.create_call(to="", agent_id="agent-1")
            with pytest.raises(ValidationError):
                await asyncio.wait_for(client.wait_closed(), timeout=2)


async def test_abnormal_disconnect_raises():
    async with running(make_gateway(drop_after_user_turn=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            await client.create_call(to="+821012345678", agent_id="agent-1")
            with pytest.raises(ConnectionClosedError):
                await asyncio.wait_for(client.wait_closed(), timeout=2)


async def test_non_object_frame_is_dropped_not_fatal():
    completed = []
    async with running(make_gateway(auto_complete=True, scalar_frame=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.CALL_COMPLETED, lambda e: completed.append(e.call_id))
            await client.create_call(to="+821012345678", agent_id="agent-1")
            await client.wait_closed()
    assert completed == ["call-1"]  # bad frame dropped, stream continued


async def test_disconnected_event_is_typed_event():
    seen = []
    async with running(make_gateway(auto_complete=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.DISCONNECTED, lambda e: seen.append(e.type))
            await client.create_call(to="+821012345678", agent_id="agent-1")
            await client.wait_closed()
    # aclose() ends the recv loop, which emits a typed DISCONNECTED Event
    assert seen == [EventType.DISCONNECTED]


async def test_session_replaced_close_raises():
    async with running(make_gateway(close_4429=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            await client.create_call(to="+821012345678", agent_id="agent-1")
            with pytest.raises(SessionReplacedError):
                await asyncio.wait_for(client.wait_closed(), timeout=2)


async def test_env_var_config(monkeypatch):
    async with running(make_gateway(auto_complete=True)) as url:
        monkeypatch.setenv("TELLO_API_KEY", RAW_KEY)
        monkeypatch.setenv("TELLO_URL", url)
        completed = []
        async with TelloClient() as client:  # no args -> read env
            client.on(EventType.CALL_COMPLETED, lambda e: completed.append(e.call_id))
            await client.create_call(to="+821012345678", agent_id="agent-1")
            await client.wait_closed()
    assert completed == ["call-1"]


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("TELLO_API_KEY", raising=False)
    with pytest.raises(ValueError):
        TelloClient()


async def test_heartbeat_pong_keeps_connection_alive():
    # Server pings mid-call; websockets auto-pongs. If the pong never arrived the
    # server's wait_for would raise and the call would not complete.
    completed = []
    async with running(make_gateway(auto_complete=True, ping_on_create=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.CALL_COMPLETED, lambda e: completed.append(e.call_id))
            await client.create_call(to="+821012345678", agent_id="agent-1")
            await client.wait_closed()

    assert completed == ["call-1"]
