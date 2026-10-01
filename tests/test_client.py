"""Integration tests driving TelloClient against an in-memory fake gateway.

The fake mimics turn-provider-gateway `/sdk`: an application-level auth
handshake (first frame must be `auth` with the raw key in `token`, server
replies `auth.ok`), inbound `{event, data}` command frames, and flat outbound
event frames.
"""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from tello import (
    AuthenticationError,
    CallAlreadyActiveError,
    CallRefusedError,
    ClientConfig,
    ConnectionClosedError,
    EventType,
    SessionReplacedError,
    TelloClient,
    TelloServerError,
    ValidationError,
)

RAW_KEY = "sdk-secret"
DTMF_KEYS = frozenset("0123456789*#")


def _call_created():
    return json.dumps(
        {
            "type": "call.created",
            "version": "1.0",
            "sessionId": "session-1",
            "callId": "call-1",
            "timestamp": "2026-07-01T00:00:00.000Z",
        }
    )


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


def _answer_accepted(request_id, message_id):
    return json.dumps(
        {
            "type": "answer.accepted",
            "version": "1.0",
            "requestId": request_id,
            "sessionId": "session-1",
            "callId": "call-1",
            "messageId": message_id,
            "timestamp": "2026-07-01T00:00:01.250Z",
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


def _auth_ok(request_id=None):
    frame = {"type": "auth.ok", "version": "1.0", "accountId": "account-1"}
    if request_id is not None:
        frame["requestId"] = request_id
    return json.dumps(frame)


def make_gateway(
    auto_complete=True,
    ping_on_create=False,
    drop_after_user_turn=False,
    scalar_frame=False,
    close_4429=False,
    api_key=RAW_KEY,
    auth_delay=0.0,
    no_auth_ok=False,
    auth_close_only=False,
    received=None,
    upgrade_sink=None,
    refuse_create=None,
    stream_failure=None,
    cleanup_window=0,
):
    async def handler(ws):
        # Used up once per gateway, not per connection, so a reconnect moves on.
        nonlocal cleanup_window, drop_after_user_turn
        if upgrade_sink is not None:
            upgrade_sink["authorization"] = ws.request.headers.get("Authorization")
            upgrade_sink["path"] = ws.request.path

        # The first application frame MUST be `auth` carrying the raw key in
        # `token`; no upgrade header or query token is used. Nothing else may be
        # processed until auth.ok.
        try:
            raw = await ws.recv()
        except ConnectionClosed:
            return
        msg = json.loads(raw)
        if received is not None:
            received.append(msg)
        data = msg.get("data", {})

        if auth_close_only:
            await ws.close(4401, "unauthenticated")
            return
        if msg.get("event") != "auth" or data.get("token") != api_key:
            await ws.send(_error("unauthenticated", "Authentication required", data.get("requestId")))
            await ws.close(4401, "unauthenticated")
            return
        if no_auth_ok:
            await asyncio.sleep(2)  # never confirm: exercise client auth-wait timeout
            return
        if auth_delay:
            await asyncio.sleep(auth_delay)
        await ws.send(_auth_ok(data.get("requestId")))

        active = False
        status = None  # the live call's current status
        stream_tasks = []

        async def fail_stream(create_request_id):
            # Like the real gateway when a call's stream fails after call.created:
            # the call is cancelled and the only frame is an error echoing the
            # createCall requestId, with no terminal event.
            nonlocal active
            await stream_failure.wait()
            active = False
            await ws.send(_error("internalError", "Internal error", create_request_id))

        async for raw in ws:
            if received is not None:
                received.append(json.loads(raw))
            msg = json.loads(raw)
            event = msg.get("event")
            data = msg.get("data", {})

            if event == "createCall":
                if active or cleanup_window:
                    # A live call continues untouched. Without one, a createCall
                    # landing in the previous call's cleanup window (contract
                    # §4.1) is refused the same way, and no call.created follows.
                    if not active:
                        cleanup_window -= 1
                    await ws.send(
                        _error("callAlreadyActive", "A call is already active", data.get("requestId"))
                    )
                    continue
                if not data.get("to"):
                    # rejected create: send error, keep socket open, no terminal
                    await ws.send(_error("toRequired", "to is required", data.get("requestId")))
                    continue
                if refuse_create is not None:
                    # outbound-gate refusal: one error echoing the createCall
                    # requestId, no call.created, socket stays open
                    await ws.send(_error(refuse_create, "Call refused", data.get("requestId")))
                    continue
                if close_4429:
                    await ws.close(4429, "session replaced")
                    return
                active = True
                await ws.send(_call_created())
                await ws.send(_status_changed("inProgress", "queued"))
                status = "inProgress"
                if scalar_frame:
                    await ws.send(json.dumps(123))  # valid JSON, non-object
                await ws.send(_user_turn(1, "Need help"))
                if drop_after_user_turn:
                    # abnormal: close mid-call, no terminal. Only the first call
                    # drops, so a test can reconnect and place another.
                    drop_after_user_turn = False
                    await ws.close()
                    return
                if ping_on_create:
                    pong_waiter = await ws.ping()
                    await asyncio.wait_for(pong_waiter, timeout=1)
                if stream_failure is not None:
                    stream_tasks.append(asyncio.create_task(fail_stream(data.get("requestId"))))
                if auto_complete:
                    await ws.send(_completed())
                    active = False
            elif event == "answer":
                if not active:
                    await ws.send(_error("noActiveCall", "No active call", data.get("requestId")))
                    continue
                await ws.send(_answer_accepted(data.get("requestId"), data.get("messageId", "message-1")))
                await ws.send(_agent_turn(2, data.get("text", "")))
            elif event == "sendDtmf":
                if not active:
                    await ws.send(_error("noActiveCall", "No active call", data.get("requestId")))
                    continue
                if set(data.get("digits", "")) - DTMF_KEYS:
                    message = "digits must contain only 0-9, *, #"
                    await ws.send(_error("dtmfDigitsInvalid", message, data.get("requestId")))
                    continue
                await ws.send(_agent_turn(2, data.get("digits", "")))
            elif event == "cancel":
                # A no-op without a live call. Otherwise the cancelled
                # call.statusChanged, carrying the status it replaced, is the
                # call's terminal event (contract §4.4).
                if active:
                    await ws.send(_status_changed("cancelled", status))
                    active = False
        for task in stream_tasks:  # socket closed: an unfired failure has no one to reach
            task.cancel()

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
                EventType.CALL_CREATED,
                EventType.CALL_STATUS_CHANGED,
                EventType.USER_TURN,
                EventType.CALL_COMPLETED,
            ):
                client.on(et, lambda e: seen.append(e.type))
            await client.create_call(to="+821012345678", prompt="call the clinic")
            await client.wait_closed()

    assert seen == ["call.created", "call.statusChanged", "user.turn", "call.completed"]


async def test_user_turn_fields():
    got = {}
    async with running(make_gateway(auto_complete=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:

            @client.on(EventType.USER_TURN)
            def _(event):
                got["index"] = event.turn_index
                got["text"] = event.text
                got["call_id"] = event.call_id

            await client.create_call(to="+821012345678")
            await client.wait_closed()

    assert got == {"index": 1, "text": "Need help", "call_id": "call-1"}


async def test_answer_produces_agent_turn():
    events = []
    async with running(make_gateway(auto_complete=False)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:

            @client.on(EventType.ANSWER_ACCEPTED)
            def _(event):
                events.append((event.type, event.request_id))

            @client.on(EventType.AGENT_TURN)
            def _(event):
                events.append((event.type, event.text))

            await client.create_call(to="+821012345678")
            await asyncio.sleep(0.05)  # let user.turn arrive
            await client.answer(text="The 2 PM slot is open.", request_id="answer-1")
            await asyncio.sleep(0.05)
            await client.cancel()
            await client.wait_closed()

    assert events == [
        ("answer.accepted", "answer-1"),
        ("agent.turn", "The 2 PM slot is open."),
    ]


async def test_send_dtmf_produces_agent_turn():
    turns = []
    async with running(make_gateway(auto_complete=False)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:

            @client.on(EventType.AGENT_TURN)
            def _(event):
                turns.append((event.turn_index, event.text))

            await client.create_call(to="+821012345678")
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


async def test_auth_is_first_frame_and_precedes_commands():
    # The auth frame (carrying the API key in `token`) is the very first frame
    # the server receives, and no business command reaches the server before it.
    received = []
    async with running(make_gateway(auto_complete=True, received=received)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            await client.create_call(to="+821012345678")
            await client.wait_closed()

    events = [m.get("event") for m in received]
    assert events[0] == "auth"
    assert received[0]["data"]["token"] == RAW_KEY
    assert "createCall" in events
    assert events.index("auth") < events.index("createCall")


async def test_no_authorization_header_or_query_token_on_upgrade():
    # The API key must not ride on the WS upgrade request nor in the URL query.
    sink = {}
    async with running(make_gateway(auto_complete=True, upgrade_sink=sink)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            await client.create_call(to="+821012345678")
            await client.wait_closed()

    assert sink["authorization"] is None
    assert RAW_KEY not in sink["path"]


async def test_business_command_blocked_until_auth_ok():
    # connect() must not return (so no command can be sent) until auth.ok. With a
    # delayed auth.ok, the first server-received frame is still auth and
    # createCall only follows after connect() unblocks.
    received = []
    async with running(make_gateway(auto_complete=True, auth_delay=0.2, received=received)) as url:
        client = TelloClient(api_key=RAW_KEY, url=url)
        await client.connect()  # blocks ~0.2s until auth.ok
        await client.create_call(to="+821012345678")
        await client.wait_closed()
        await client.aclose()

    events = [m.get("event") for m in received]
    assert events[0] == "auth"
    assert events.index("auth") < events.index("createCall")


async def test_unauthenticated_error_frame_raises_from_connect():
    # Server replies with an `unauthenticated` error frame (+4401 close).
    async with running(make_gateway()) as url:
        client = TelloClient(api_key="wrong-key", url=url)
        with pytest.raises(AuthenticationError):
            await client.connect()
        await client.aclose()  # safe even though connect() failed


async def test_4401_close_without_error_frame_raises_from_connect():
    # Server closes with 4401 and no error frame during the auth handshake.
    async with running(make_gateway(auth_close_only=True)) as url:
        client = TelloClient(api_key=RAW_KEY, url=url)
        with pytest.raises(AuthenticationError):
            await client.connect()
        await client.aclose()


async def test_auth_ok_timeout_raises_from_connect():
    # Server never sends auth.ok; the client's open_timeout bounds the wait.
    async with running(make_gateway(no_auth_ok=True)) as url:
        client = TelloClient(config=ClientConfig(api_key=RAW_KEY, url=url, open_timeout=0.3))
        with pytest.raises(AuthenticationError):
            await asyncio.wait_for(client.connect(), timeout=2)
        await client.aclose()


async def test_api_key_never_in_auth_exception_message():
    secret = "tello_live_topsecret_value"
    async with running(make_gateway()) as url:
        client = TelloClient(api_key=secret, url=url)
        with pytest.raises(AuthenticationError) as exc_info:
            await client.connect()
        assert secret not in str(exc_info.value)
        await client.aclose()


async def test_rejected_create_missing_to_unblocks_wait_closed():
    # gateway rejects create_call (empty to) with an error frame and no
    # terminal/close; wait_closed() must raise, not hang.
    async with running(make_gateway(auto_complete=False)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            await client.create_call(to="")
            with pytest.raises(ValidationError):
                await asyncio.wait_for(client.wait_closed(), timeout=2)


async def test_other_command_error_does_not_end_call_wait():
    # Contract §6: a failed command does not end the call. A sendDtmf error
    # (echoing its own requestId, or carrying none) only reaches ERROR handlers;
    # wait_closed() keeps waiting for the call's terminal event.
    errors = []
    created = asyncio.Event()
    both_failed = asyncio.Event()
    async with running(make_gateway(auto_complete=False)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.CALL_CREATED, lambda e: created.set())

            @client.on(EventType.ERROR)
            def _(event):
                errors.append((event.code, event.request_id))
                if len(errors) == 2:
                    both_failed.set()

            await client.create_call(to="+821012345678")
            waiting = asyncio.create_task(client.wait_closed())
            await asyncio.wait_for(created.wait(), timeout=2)
            await client.send_dtmf(digits="12x", request_id="dtmf-1")
            await client.send_dtmf(digits="12x")  # no requestId on the command or its error
            await asyncio.wait_for(both_failed.wait(), timeout=2)
            await asyncio.sleep(0.05)
            assert not waiting.done()  # the call is still live

            await client.cancel()  # the fake gateway ends the call with a cancelled status
            await asyncio.wait_for(waiting, timeout=2)

    assert errors == [("dtmfDigitsInvalid", "dtmf-1"), ("dtmfDigitsInvalid", None)]


async def test_create_call_refusal_ends_call_wait():
    # An outbound-gate refusal is one error echoing the createCall requestId,
    # with no call.created and no terminal event; wait_closed() raises it.
    async with running(make_gateway(refuse_create="insufficientCredit")) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            await client.create_call(to="+821012345678", request_id="create-1")
            with pytest.raises(CallRefusedError) as exc_info:
                await asyncio.wait_for(client.wait_closed(), timeout=2)

    assert exc_info.value.code == "insufficientCredit"


async def test_create_call_failure_after_call_created_ends_call_wait():
    # A stream failure after call.created ends the call with one error echoing
    # the createCall requestId and no terminal event. The earlier sendDtmf
    # error must not have ended the wait in its place.
    stream_failure = asyncio.Event()
    created = asyncio.Event()
    dtmf_failed = asyncio.Event()
    async with running(make_gateway(auto_complete=False, stream_failure=stream_failure)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.CALL_CREATED, lambda e: created.set())
            client.on(EventType.ERROR, lambda e: dtmf_failed.set())
            await client.create_call(to="+821012345678")
            await asyncio.wait_for(created.wait(), timeout=2)
            await client.send_dtmf(digits="12x", request_id="dtmf-1")
            await asyncio.wait_for(dtmf_failed.wait(), timeout=2)

            stream_failure.set()
            with pytest.raises(TelloServerError) as exc_info:
                await asyncio.wait_for(client.wait_closed(), timeout=2)

    assert exc_info.value.code == "internalError"


async def test_create_call_during_active_call_keeps_tracking_that_call():
    # A second create_call during a live call is refused with callAlreadyActive
    # and the original call continues, so a later failure of the original
    # call's stream must still end the wait.
    stream_failure = asyncio.Event()
    refused = asyncio.Event()
    async with running(make_gateway(auto_complete=False, stream_failure=stream_failure)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.ERROR, lambda e: refused.set())
            await client.create_call(to="+821012345678")
            await client.create_call(to="+821012345678")
            await asyncio.wait_for(refused.wait(), timeout=2)

            stream_failure.set()
            with pytest.raises(TelloServerError):
                await asyncio.wait_for(client.wait_closed(), timeout=2)


async def test_call_already_active_answering_the_opening_create_call_ends_call_wait():
    # T5. Right after a call ends the gateway still holds the session until it
    # has cleaned that call up (contract §4.1): a createCall landing in that
    # window gets callAlreadyActive and no call.created. That call never
    # started, so the wait raises, and a retry starts a fresh call.
    errors = []
    completed = []
    async with running(make_gateway(auto_complete=True, cleanup_window=1)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.ERROR, lambda e: errors.append((e.code, e.request_id)))
            client.on(EventType.CALL_COMPLETED, lambda e: completed.append(e.call_id))
            await client.create_call(to="+821012345678", request_id="create-a")
            with pytest.raises(CallAlreadyActiveError):
                await asyncio.wait_for(client.wait_closed(), timeout=2)

            await client.create_call(to="+821012345678", request_id="create-b")
            await asyncio.wait_for(client.wait_closed(), timeout=2)
            assert completed == ["call-1"]  # the retry's wait ended at its call.completed

    assert errors == [("callAlreadyActive", "create-a")]


async def test_create_call_refused_during_a_live_call_keeps_the_pending_wait():
    # T6. A createCall sent during a live call is refused with callAlreadyActive
    # and the live call goes on. That refusal is only an event: a wait already
    # pending on the live call stays with it and ends with the live call's own
    # createCall failure.
    stream_failure = asyncio.Event()
    created = asyncio.Event()
    refused = asyncio.Event()
    errors = []
    async with running(make_gateway(auto_complete=False, stream_failure=stream_failure)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.CALL_CREATED, lambda e: created.set())

            @client.on(EventType.ERROR)
            def _(event):
                errors.append((event.code, event.request_id))
                refused.set()

            await client.create_call(to="+821012345678", request_id="create-a")
            await asyncio.wait_for(created.wait(), timeout=2)
            waiting = asyncio.create_task(client.wait_closed())
            await client.create_call(to="+821012345678", request_id="create-b")
            await asyncio.wait_for(refused.wait(), timeout=2)

            stream_failure.set()
            with pytest.raises(TelloServerError):
                await asyncio.wait_for(waiting, timeout=2)

    assert errors == [("callAlreadyActive", "create-b"), ("internalError", "create-a")]


async def test_wait_ends_with_its_own_call_when_a_terminal_handler_starts_the_next():
    # T7. A wait started during call A returns when A ends, even though A's
    # terminal handler has already started call B. B is a call of its own: an
    # error echoing A's createCall requestId does not end it, and a new wait
    # follows B to its own terminal event.
    calls_created = asyncio.Queue()
    errors = []
    follow_ups = []
    async with running(make_gateway(auto_complete=False)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.CALL_CREATED, calls_created.put_nowait)
            client.on(EventType.ERROR, lambda e: errors.append((e.code, e.request_id)))

            @client.on(EventType.CALL_STATUS_CHANGED)
            async def _(event):
                if event.status == "cancelled" and not follow_ups:
                    follow_ups.append(event)
                    await client.create_call(to="+821012345678", request_id="create-b")

            await client.create_call(to="+821012345678", request_id="create-a")
            await asyncio.wait_for(calls_created.get(), timeout=2)
            first = asyncio.create_task(client.wait_closed())
            await client.cancel()  # A's terminal, whose handler starts B
            await asyncio.wait_for(first, timeout=2)

            await asyncio.wait_for(calls_created.get(), timeout=2)
            second = asyncio.create_task(client.wait_closed())
            # Reusing A's createCall requestId on another command draws an
            # error that echoes it.
            await client.send_dtmf(digits="12x", request_id="create-a")
            await client.cancel()  # B's terminal
            await asyncio.wait_for(second, timeout=2)

    assert errors == [("dtmfDigitsInvalid", "create-a")]


async def test_reconnect_leaves_the_dropped_call_behind():
    # T8. A call cut off by a socket drop is over. After reconnecting, an error
    # echoing the dropped call's createCall requestId does not end the new
    # call's wait; the new call's own terminal event does.
    errors = []
    async with running(make_gateway(auto_complete=False, drop_after_user_turn=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.ERROR, lambda e: errors.append((e.code, e.request_id)))
            await client.create_call(to="+821012345678", request_id="create-a")
            with pytest.raises(ConnectionClosedError):
                await asyncio.wait_for(client.wait_closed(), timeout=2)

            await client.connect()
            await client.create_call(to="+821012345678", request_id="create-c")
            waiting = asyncio.create_task(client.wait_closed())
            # Reusing the dropped call's createCall requestId on another
            # command draws an error that echoes it.
            await client.send_dtmf(digits="12x", request_id="create-a")
            await client.cancel()
            await asyncio.wait_for(waiting, timeout=2)

    assert errors == [("dtmfDigitsInvalid", "create-a")]


async def test_reconnect_from_disconnected_handler_leaves_the_new_connection_alone():
    # A DISCONNECTED handler that reconnects runs while the dropped
    # connection's receive loop is still finishing. The dropped call's wait
    # still reports the drop, and that old loop must not mark the new
    # connection closed: a call on it is waited on until its own terminal.
    statuses = []
    reconnected = asyncio.Event()
    async with running(make_gateway(auto_complete=False, drop_after_user_turn=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.CALL_STATUS_CHANGED, lambda e: statuses.append(e.status))

            @client.on(EventType.DISCONNECTED)
            async def _(event):
                if not reconnected.is_set():  # the final aclose() must not reconnect
                    await client.connect()
                    reconnected.set()

            await client.create_call(to="+821012345678", request_id="create-a")
            with pytest.raises(ConnectionClosedError):
                await asyncio.wait_for(client.wait_closed(), timeout=2)
            await asyncio.wait_for(reconnected.wait(), timeout=2)

            await client.create_call(to="+821012345678", request_id="create-c")

            async def statuses_when_the_wait_ends():
                await client.wait_closed()
                return list(statuses)

            waiting = asyncio.create_task(statuses_when_the_wait_ends())
            await client.cancel()
            assert (await asyncio.wait_for(waiting, timeout=2))[-1] == "cancelled"


@pytest.mark.parametrize("connect_first", [False, True], ids=["never-connected", "after-aclose"])
async def test_create_call_that_cannot_be_sent_leaves_no_call_running(connect_first):
    # T9. A createCall that never reaches the gateway starts no call: it
    # raises, and the wait after it reports that same failure instead of
    # hanging.
    async with running(make_gateway()) as url:
        client = TelloClient(api_key=RAW_KEY, url=url)
        if connect_first:
            await client.connect()
            await client.aclose()
        with pytest.raises(ConnectionClosedError) as sent:
            await client.create_call(to="+821012345678")
        with pytest.raises(ConnectionClosedError) as waited:
            await asyncio.wait_for(client.wait_closed(), timeout=2)

    assert waited.value is sent.value


async def test_create_call_wire_frame_has_no_agent_id_key():
    # Contract: the createCall data payload must never contain an agentId key.
    received = []
    async with running(make_gateway(auto_complete=True, received=received)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            await client.create_call(
                to="+821012345678",
                prompt="call the clinic",
                metadata={"src": "test"},
                request_id="r1",
            )
            await client.wait_closed()

    create_frames = [m for m in received if m.get("event") == "createCall"]
    assert len(create_frames) == 1
    data = create_frames[0]["data"]
    assert "agentId" not in data
    assert data == {
        "to": "+821012345678",
        "prompt": "call the clinic",
        "metadata": {"src": "test"},
        "requestId": "r1",
    }


@pytest.mark.parametrize("caller_request_id", [None, "", "caller-req-1"])
async def test_create_call_always_sends_request_id(caller_request_id):
    # The gateway echoes a command's requestId on its error frame, so every
    # createCall carries one: the caller's when non-empty, else a generated id.
    received = []
    async with running(make_gateway(auto_complete=True, received=received)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            await client.create_call(to="+821012345678", request_id=caller_request_id)
            await client.wait_closed()

    [create_frame] = [m for m in received if m.get("event") == "createCall"]
    sent = create_frame["data"].get("requestId")
    assert isinstance(sent, str) and sent
    if caller_request_id:
        assert sent == caller_request_id


async def test_abnormal_disconnect_raises():
    async with running(make_gateway(drop_after_user_turn=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            await client.create_call(to="+821012345678")
            with pytest.raises(ConnectionClosedError):
                await asyncio.wait_for(client.wait_closed(), timeout=2)


async def test_non_object_frame_is_dropped_not_fatal():
    completed = []
    async with running(make_gateway(auto_complete=True, scalar_frame=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.CALL_COMPLETED, lambda e: completed.append(e.call_id))
            await client.create_call(to="+821012345678")
            await client.wait_closed()
    assert completed == ["call-1"]  # bad frame dropped, stream continued


async def test_disconnected_event_is_typed_event():
    seen = []
    async with running(make_gateway(auto_complete=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            client.on(EventType.DISCONNECTED, lambda e: seen.append(e.type))
            await client.create_call(to="+821012345678")
            await client.wait_closed()
    # aclose() ends the recv loop, which emits a typed DISCONNECTED Event
    assert seen == [EventType.DISCONNECTED]


async def test_session_replaced_close_raises():
    async with running(make_gateway(close_4429=True)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url) as client:
            await client.create_call(to="+821012345678")
            with pytest.raises(SessionReplacedError):
                await asyncio.wait_for(client.wait_closed(), timeout=2)


async def test_env_var_config(monkeypatch):
    async with running(make_gateway(auto_complete=True)) as url:
        monkeypatch.setenv("TELLO_API_KEY", RAW_KEY)
        monkeypatch.setenv("TELLO_URL", url)
        completed = []
        async with TelloClient() as client:  # no args -> read env
            client.on(EventType.CALL_COMPLETED, lambda e: completed.append(e.call_id))
            await client.create_call(to="+821012345678")
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
            await client.create_call(to="+821012345678")
            await client.wait_closed()

    assert completed == ["call-1"]


@pytest.mark.parametrize(
    "suffix, path, extra",
    [
        ("", "/sdk", {}),
        ("?region=kr&sdk=custom", "/sdk", {"region": ["kr"]}),
        ("/v2/sdk?a=1%202", "/sdk/v2/sdk", {"a": ["1 2"]}),
    ],
)
async def test_upgrade_url_identifies_sdk(suffix, path, extra):
    # The upgrade URL carries sdk/version/protocol; the caller's path and other
    # query keys survive, and SDK keys override same-named caller keys.
    from urllib.parse import parse_qs, urlsplit

    from tello import PROTOCOL_VERSION, __version__

    sink = {}
    async with running(make_gateway(auto_complete=True, upgrade_sink=sink)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url + suffix):
            pass

    sent = urlsplit(sink["path"])
    assert sent.path == path
    assert parse_qs(sent.query) == {
        **extra,
        "sdk": ["python"],
        "version": [__version__],
        "protocol": [PROTOCOL_VERSION],
    }


@pytest.mark.parametrize(
    "suffix, kept",
    [
        ("?a=1%202&flag&s=%FF", "a=1%202&flag&s=%FF"),
        ("?%73dk=custom&x=1&&version=9&pro%74ocol=0", "x=1"),
        ("?b=1;c=2&s+dk=k", "b=1;c=2&s+dk=k"),
    ],
)
async def test_upgrade_url_keeps_caller_query_verbatim(suffix, kept):
    # Caller query pairs reach the server byte-for-byte; only pairs whose
    # form-decoded key is an identity key are dropped before ours are appended.
    from urllib.parse import quote, urlsplit

    from tello import PROTOCOL_VERSION, __version__

    sink = {}
    async with running(make_gateway(auto_complete=True, upgrade_sink=sink)) as url:
        async with TelloClient(api_key=RAW_KEY, url=url + suffix):
            pass

    ident = (
        f"sdk=python&version={quote(__version__, safe='')}"
        f"&protocol={quote(PROTOCOL_VERSION, safe='')}"
    )
    assert urlsplit(sink["path"]).query == f"{kept}&{ident}"



async def test_default_url_identifies_sdk(monkeypatch):
    # Neither url= nor TELLO_URL: the client dials the production gateway,
    # identifying itself. The dial is refused, so no network is touched.
    from urllib.parse import parse_qs, urlsplit

    from tello import PROTOCOL_VERSION, __version__
    from tello import client as client_mod

    opened = []

    async def fake_connect(url, **kwargs):
        opened.append(url)
        raise OSError("stop")

    monkeypatch.delenv("TELLO_URL", raising=False)
    monkeypatch.setattr(client_mod.websockets, "connect", fake_connect)
    with pytest.raises(OSError):
        await TelloClient(api_key=RAW_KEY).connect()

    sent = urlsplit(opened[0])
    assert (sent.scheme, sent.netloc, sent.path) == ("wss", "api.telloai.io", "/sdk")
    assert parse_qs(sent.query) == {
        "sdk": ["python"],
        "version": [__version__],
        "protocol": [PROTOCOL_VERSION],
    }
