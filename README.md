# tello-sdk (Python)

> 리포: `tello-python` · PyPI 배포명: `tello-sdk` · import: `tello`

Tello SDK for Python — a thin **WebSocket** realtime client for the
turn-provider-gateway `/sdk` endpoint. The SDK is the "conversation brain":
the gateway streams each caller turn from a live phone call, and your handler's
reply is forwarded back into the call.

> Transport is WebSocket only. There is no REST or webhook surface. The protocol
> contract lives in [`docs/protocol/sdk-ws.v1.md`](docs/protocol/sdk-ws.v1.md).

## 1. Install

```bash
pip install tello-sdk        # requires Python >= 3.10; imports as `tello`
```

## 2. API key

The key is sent as `Authorization: Bearer <api_key>` on the WS upgrade request.
Issue one in the portal (Agent settings → Advanced → Agent-linked / SDK).

Pass it explicitly or via environment variables:

```bash
export TELLO_API_KEY="tello_live_xxx"
export TELLO_URL="ws://localhost:3000/sdk"   # optional; defaults to ws://localhost:3000/sdk
```

`TelloClient()` with no arguments then reads `TELLO_API_KEY` / `TELLO_URL`.

## 3. Connect + start a call

```python
import asyncio
from tello import TelloClient, EventType

async def main():
    async with TelloClient(api_key="tello_live_xxx", url="ws://localhost:3000/sdk") as client:
        @client.on(EventType.USER_TURN)
        async def on_user_turn(event):
            await client.answer(text="확인했습니다. 계속 말씀해주세요.")

        await client.create_call(to="+821012345678", agent_id="agent-1", prompt="예약 확인")
        await client.wait_closed()

asyncio.run(main())
```

`TelloClient(...)` is the constructor (Python has no `new`). The `async with`
form is sugar for `connect()` / `aclose()`; use them explicitly if you prefer:

```python
client = TelloClient(api_key="tello_live_xxx", url="ws://localhost:3000/sdk")
await client.connect()
client.on(EventType.USER_TURN, on_user_turn)
await client.create_call(to="+821012345678", agent_id="agent-1", prompt="예약 확인")
await client.wait_closed()
await client.aclose()
```

## 4. Realtime turn events (pub/sub)

Subscribe handlers (sync or async) per event type via `client.on(...)`:

| `EventType` | value | payload fields |
| --- | --- | --- |
| `USER_TURN` | `user.turn` | `turn_index`, `text` |
| `AGENT_TURN` | `agent.turn` | `turn_index`, `text` |
| `CALL_STATUS_CHANGED` | `call.status_changed` | `status`, `previous_status` |
| `CALL_COMPLETED` | `call.completed` | `status` |
| `CALL_NO_ANSWER` | `call.no_answer` | `status`, `failure_reason?` |
| `CALL_FAILED` | `call.failed` | `status`, `failure_reason?` |
| `ERROR` | `error` | `code`, `message`, `request_id?`, `question?` |
| `DISCONNECTED` | `disconnected` | SDK-local; emitted when the WS closes |

Commands: `await client.create_call(to, agent_id, prompt="", metadata=None)`,
`await client.answer(text, message_id=None)`, `await client.cancel()`.

`await client.wait_closed()` resolves when the call reaches a terminal state
(`call.completed` / `call.no_answer` / `call.failed`, or a cancelled status) or
the connection closes.

## 5. Error handling

Gateway error frames map 1:1 to exceptions
(see [`docs/errors/errors.v1.json`](docs/errors/errors.v1.json)):

| gateway `code` | exception |
| --- | --- |
| `unauthenticated` | `AuthenticationError` (also close code 4401) |
| `to_required` | `ValidationError` |
| `agent_id_required` | `ValidationError` |
| `call_already_active` | `CallAlreadyActiveError` |
| `no_active_call` | `NoActiveCallError` |
| `call_rejected` | `CallRejectedError` (with `.question`) |
| `internal_error` | `TelloServerError` |

Command-level errors are also delivered to `EventType.ERROR` subscribers without
closing the socket. `wait_closed()` re-raises the relevant error so a failed
`create_call` (e.g. `to_required`, `agent_id_required`, `call_rejected`) does not hang:

- auth failure → `AuthenticationError`
- a call-start rejection → its mapped exception above
- the connection dropping mid-call → `ConnectionClosedError`
- the session being displaced (close 4429) → `SessionReplacedError`

The gateway drives a WS-level ping heartbeat; `websockets` answers pongs
automatically. There is no reconnect/resume — treat an abnormal close as
reconnect-worthy and restart the call.

## 6. Version compatibility

`tello-sdk 0.1.x` implements Tello WS protocol `1.0`.
