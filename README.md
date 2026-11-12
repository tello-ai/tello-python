**English** | [한국어](https://github.com/tello-ai/tello-python/blob/main/README.ko.md)

# tello-ai-sdk (Python)

> repo: `tello-python` · PyPI package: `tello-ai-sdk` · import: `tello`

Tello SDK for Python — a thin **WebSocket** realtime client for the
API gateway (api-gateway) `/sdk` endpoint, plus `TelloApi`, a client for the
public REST resource API. The WebSocket client is the "conversation brain":
the gateway streams each caller turn from a live phone call, and your handler's
reply is forwarded back into the call.

> The realtime protocol contract lives in [`docs/protocol/sdk-ws.v1.md`](https://github.com/tello-ai/tello-python/blob/main/docs/protocol/sdk-ws.v1.md).
> The REST resource API (tools, agents, crews, call drafts) is in §6.

## 1. Install

```bash
pip install tello-ai-sdk     # requires Python >= 3.10; imports as `tello`
```

## 2. API key

The key authenticates the connection through an application-level handshake:
right after the socket opens the SDK sends an `auth` frame carrying the key in
its `token` field and waits for the server's `auth.ok` before anything else
runs. The key is never placed on the WS upgrade request or in the URL query.
This is fully internal — you never call auth yourself; `connect()` (and `async
with`) simply does not succeed until authentication has. Issue a key in the portal
(Agent settings → Advanced → Agent-linked / SDK).

Pass it explicitly or via environment variables:

```bash
export TELLO_API_KEY="tello_live_xxx"
export TELLO_URL="wss://api.telloai.io/sdk"   # optional; defaults to wss://api.telloai.io/sdk
```

`TelloClient()` with no arguments then reads `TELLO_API_KEY` / `TELLO_URL`.
The client appends `sdk=python&version=<package version>&protocol=<PROTOCOL_VERSION>` to the URL query (other path/query parts are kept); the server only logs them.

## 3. Connect + start a call

```python
import asyncio
from tello import TelloClient, EventType

async def main():
    async with TelloClient(api_key="tello_live_xxx", url="wss://api.telloai.io/sdk") as client:
        @client.on(EventType.USER_TURN)
        async def on_user_turn(event):
            await client.answer(text="확인했습니다. 계속 말씀해주세요.")

        await client.create_call(to="+821012345678", prompt="예약 확인")
        await client.wait_closed()

asyncio.run(main())
```

`TelloClient(...)` is the constructor (Python has no `new`). The `async with`
form is sugar for `connect()` / `aclose()`; use them explicitly if you prefer:

```python
client = TelloClient(api_key="tello_live_xxx", url="wss://api.telloai.io/sdk")
await client.connect()
client.on(EventType.USER_TURN, on_user_turn)
await client.create_call(to="+821012345678", prompt="예약 확인")
await client.wait_closed()
await client.aclose()
```

## 4. Realtime turn events (pub/sub)

Subscribe handlers (sync or async) per event type via `client.on(...)`:

| `EventType` | value | payload fields |
| --- | --- | --- |
| `CALL_CREATED` | `call.created` | `call_id`, `session_id` |
| `USER_TURN` | `user.turn` | `turn_index`, `text` |
| `AGENT_TURN` | `agent.turn` | `turn_index`, `text` |
| `ANSWER_ACCEPTED` | `answer.accepted` | `request_id?`, `message_id` |
| `DTMF_ACCEPTED` | `dtmf.accepted` | `request_id?`, `message_id`, `digits` |
| `CALL_SUMMARY` | `call.summary` | `request_id?`, `status`, `duration_seconds?`, `transcript?`, `summary?`, `credit_charged?` |
| `CALL_STATUS_CHANGED` | `call.statusChanged` | `status`, `previous_status` |
| `CALL_COMPLETED` | `call.completed` | `status` |
| `CALL_NO_ANSWER` | `call.noAnswer` | `status`, `failure_reason?` |
| `CALL_FAILED` | `call.failed` | `status`, `failure_reason?` |
| `ERROR` | `error` | `code`, `message`, `request_id?`, `question?` |
| `DISCONNECTED` | `disconnected` | SDK-local; emitted when the WS closes |

Payload fields above are the Python attribute names; the wire frames themselves
use camelCase keys (`sessionId`, `callId`, `turnIndex`, `previousStatus`,
`failureReason`, `requestId`). An unknown `type` falls back to the base `Event`
so forward-compatible additions still reach subscribers.

Commands: `await client.create_call(to, prompt="", metadata=None, request_id=None)`,
`await client.answer(text, message_id=None, request_id=None)`,
`await client.send_dtmf(digits, message_id=None, request_id=None)`, `await client.cancel()`,
`await client.get_summary(call_id, request_id=None)`. `create_call` always sends
a `requestId`: the one you pass, or a generated UUID when you omit it. Give each
command its own `request_id`, or omit it (see §5).

`await client.wait_closed()` resolves when the call reaches a terminal state
(`call.completed` / `call.noAnswer` / `call.failed`, or a `call.statusChanged`
with status `cancelled`) or the connection closes. After `cancel()`, the gateway
ends the call with that cancelled `call.statusChanged` (its `previous_status` is
the status before the cancel); no `call.completed` follows. A wait in progress
returns when its own call ends, even if a handler has already started a
follow-up call; call `wait_closed()` again to wait for the follow-up. It raises
instead when the call's `create_call` fails (see §5); an error from any other
command does not end the wait.

## 5. Error handling

Gateway error frames map 1:1 to exceptions
(see [`docs/errors/errors.v1.json`](https://github.com/tello-ai/tello-python/blob/main/docs/errors/errors.v1.json)):

| gateway `code` | exception |
| --- | --- |
| `unauthenticated` | `AuthenticationError` (auth handshake; also close code 4401) |
| `ipNotAllowed` | `AuthenticationError` (auth handshake; the server key's allowed IP list excludes this connection; close 4401; `.ip` is the address judged) |
| `insufficientScope` | `PermissionDeniedError` (the server key lacks the command's scope; the connection stays open; `.required_scope` names it) |
| `toRequired` | `ValidationError` |
| `callIdRequired` | `ValidationError` |
| `callNotFound` | `ValidationError` |
| `callNotCompleted` | `ValidationError` |
| `dtmfDigitsRequired` | `ValidationError` |
| `dtmfDigitsInvalid` | `ValidationError` |
| `callAlreadyActive` | `CallAlreadyActiveError` |
| `noActiveCall` | `NoActiveCallError` |
| `callRejected` | `CallRejectedError` (with `.question`) |
| `internalError` | `TelloServerError` |

Every error carries the gateway code on `.code` — branch on that, never on
`.args[0]`, which is display text the gateway may reword.

`createCall` can also be refused before any call exists — no `call.created`, no
`callId`, no charge. The gateway never retries these; any retry policy is yours.

| gateway `code` | exception | what to do |
| --- | --- | --- |
| `insufficientCredit` | `CallRefusedError` | tell the user to top up; do not resend |
| `concurrentLimitExceeded` | `CallRefusedError` | wait for one of your own calls to end, then retry |
| `callerNotVerified` | `CallRefusedError` | tell the user to verify the number; do not resend |
| `noRepresentativeNumber` | `CallRefusedError` | tell the user to configure a caller number; do not resend |
| `callProviderUnauthorized` | `CallProviderError` | service fault; report it, resending never helps |
| `callProviderDraining` | `CallProviderError` | retry later at your own pace |
| `callProviderUnavailable` | `CallProviderError` | retry later at your own pace |
| `callSetupFailed` | `CallProviderError` | surface as a failure and report it |

Command-level errors are also delivered to `EventType.ERROR` subscribers without
closing the socket. Only an error answering the call's own `create_call` ends
the call: `create_call` always sends a `requestId` (generated when you omit it)
and the gateway echoes it on the error frame, which is how the SDK tells that
error apart. Errors from `answer`, `send_dtmf`, `get_summary`, and `cancel` do
not end the call; they are delivered only as `EventType.ERROR` events, and
`wait_closed()` keeps waiting for the call's terminal event. So give each
command its own `request_id`, or omit it: never reuse the `create_call`
requestId on another command, because an error answering that command would
then end the wait. `wait_closed()` re-raises the relevant error so a failed
`create_call` (e.g. `toRequired`, `callRejected`) does not hang:

- auth failure (`unauthenticated` or `ipNotAllowed` frame, close 4401, or `auth.ok` timeout) → `AuthenticationError`, raised from `connect()`
- the gateway unable to check the key during auth (`internalError` frame or close 1011) → `TelloServerError`, raised from `connect()`; the key was not refused, so connect again later
- a `create_call` error (a refusal before `call.created`, or a failure after it) → its mapped exception above
- `callAlreadyActive` → `CallAlreadyActiveError`, but only when it answers the `create_call` that started the call: the gateway is still finishing the previous call, so this one never started. Retry shortly. Answering a `create_call` sent during a live call, it is only an `EventType.ERROR` event and the live call continues. `noActiveCall` never ends the wait
- the connection dropping mid-call → `ConnectionClosedError`
- the session being displaced (close 4429) → `SessionReplacedError`

An `EventType.ERROR` handler receives an `ErrorEvent`, not an exception. To turn
it into the typed exception from the tables above, pass its fields to
`exception_for` from `tello.errors`:

```python
from tello import CallRefusedError, EventType
from tello.errors import exception_for

@client.on(EventType.ERROR)
def on_error(event):
    error = exception_for(event.code, event.message, event.question)
    if isinstance(error, CallRefusedError):
        print(f"refused: {error.code}")
```

The gateway drives a WS-level ping heartbeat; `websockets` answers pongs
automatically. There is no reconnect/resume — treat an abnormal close as
reconnect-worthy and restart the call.

## 6. REST resource API (`TelloApi`)

`TelloApi` is a separate client for the public REST API: tools, agents and
crews (create, read, update, delete), agent and crew lists, crew generation
from a goal, and call drafts. It needs no extra dependency (the standard
library's `urllib`, run off the event loop). Bodies and results are plain
`dict[str, Any]`, so fields this SDK does not know yet are kept.

```python
import asyncio
from tello import TelloApi, TelloApiError

async def main():
    api = TelloApi()  # reads TELLO_API_KEY (and TELLO_API_URL, if set)
    agents = await api.agents.list()
    tool = await api.tools.create(
        {"type": "endCall", "name": "End call", "functionName": "end_call"},
        idempotency_key="tool-end-call-001",
    )
    await api.tools.update(tool["id"], {"description": "Ends the call politely"})

asyncio.run(main())
```

- **Key**: `TelloApi(api_key=...)`, else `TELLO_API_KEY` (same rule and error as
  `TelloClient`). It is sent as `Authorization: Bearer <key>` and never appears in
  `repr()` or error messages.
- **URL**: `api_url=...`, else `TELLO_API_URL`, else `https://api.telloai.io/v1`.
  Only `https`; `http` only for `127.0.0.1`, `localhost` or `::1` (tests).
- **Timeouts**: 30 s for reads (`list`, `get`); 120 s for writes (tool, agent
  and crew create/update/delete, `crews.generate` and the three `call_drafts`
  requests). Override with `timeout=` / `long_timeout=` (seconds).
- **No automatic retries.** Retrying (with the same idempotency key) is yours.
- Every request sends `User-Agent: tello-python-sdk/<version>`.

| method | HTTP | success | returns |
| --- | --- | --- | --- |
| `tools.list(*, limit=None, cursor=None)` | `GET /tools` | 200 | `{"data": [...], "nextCursor": str \| None}` |
| `tools.get(id)` | `GET /tools/{id}` | 200 | tool |
| `tools.create(body, *, idempotency_key=None)` | `POST /tools` | 201 | tool (with `revision`) |
| `tools.update(id, patch)` | `PATCH /tools/{id}` | 200 | tool |
| `tools.delete(id)` | `DELETE /tools/{id}` | 204 | `None` |
| `agents.list()` | `GET /agents` | 200 | `{"data": [{"id", "name", "description", "isDefault"}]}` |
| `agents.get` / `create` / `update` / `delete` | `/agents[/{id}]` | 200 / 201 / 200 / 204 | agent / `None` |
| `crews.list()` | `GET /crews` | 200 | `{"data": [...]}` |
| `crews.get` / `create` / `update` / `delete` | `/crews[/{id}]` | 200 / 201 / 200 / 204 | crew / `None` |
| `crews.generate(body, *, idempotency_key=None)` | `POST /crews/generate` | 202 (200: existing job of the same goal) | job `{"id", "status": "running", ...}` |
| `crews.generate_and_wait(body, *, poll_interval=2.0, timeout=600.0, idempotency_key=None)` | generate, then poll | — | finished job (`succeeded` or `failed`) |
| `crew_generations.get(id)` | `GET /crew-generations/{id}` | 200 | job (`running` / `succeeded` / `failed`) |
| `call_drafts.create(body, *, idempotency_key=None)` | `POST /call-drafts` | 201 | draft |
| `call_drafts.revise(draft_id, request, *, idempotency_key=None)` | `POST /call-drafts/{id}/revise` `{"request": ...}` | 200 | draft with a **new id** |
| `call_drafts.confirm(draft_id, *, idempotency_key=None)` | `POST /call-drafts/{id}/confirm` (no body) | 201 | the placed call |

> **Writes go live at once.** Creating, updating or deleting a tool, agent or
> crew (and `crews.generate`) saves, deploys and publishes it: the next call
> uses it. There is no draft or staging step.
>
> **`call_drafts.confirm` places a real, billed phone call.** `call_drafts.create`
> may also call at once when the agent's scenario is ready (`status` `confirmed`
> with a `callId`). Every draft `status` (`pendingConfirmation`,
> `needsClarification`, `refused`, `confirmed`) is a `201` success, not an error.

Idempotency keys are sent only when you pass `idempotency_key` (create, generate,
draft create/revise). `call_drafts.confirm` always sends one: yours, or a
generated UUID v4. A key must be 1–255 printable ASCII characters (0x20–0x7E) with no comma,
otherwise `ValueError` is raised before any request; so is an empty id.
`generate_and_wait` returns a `failed` job instead of raising (branch on
`job["status"]`) and raises `TimeoutError` with the job id when it is still
running after `timeout`.

### REST errors

An error response raises `TelloApiError` (a `TelloError`) with `status` (HTTP),
`code` (the envelope's `error`, verbatim snake_case), `message`, `data` (dict or
`None`) and `idempotency_key` (the key sent, or `None`). A response that is not
the error envelope (a proxy page, for example) has `code = "http_<status>"`; an
undocumented success status or a body that is not a JSON object has
`code = "invalid_response"`. When no response arrives (connection failure or
timeout) `TelloApiConnectionError` is raised with `idempotency_key` and the
cause on `__cause__` — **a write that fails this way may still have been
applied**: check with `get`/`list` before resending.

| HTTP | `code` | meaning |
| --- | --- | --- |
| 401 | `unauthenticated` | key missing, wrong or revoked |
| 403 | `insufficient_scope` | the key lacks the scope (`data.requiredScope`) |
| 404 | `tool_not_found` / `agent_not_found` / `crew_not_found` | no such item in this account |
| 404 | `crew_generation_not_found` / `draft_not_found` | no such job or draft |
| 409 | `idempotency_key_reused` | the key was used for a different request |
| 409 | `crew_generation_in_progress` | another goal is being built (`data.id`) |
| 409 | `draft_already_confirmed` | the draft was confirmed (`data.callId`) |
| 502 | `write_outcome_unknown` | the write may have been applied; check before creating again |
| 503 | `upstream_unavailable` | not processed; resend later |

The full list is in the public REST error reference. Branch on `code`, never on
`message`:

```python
from tello import TelloApiConnectionError, TelloApiError

try:
    call = await api.call_drafts.confirm(draft_id)
except TelloApiError as e:
    if e.code == "draft_already_confirmed":
        print("already placed:", e.data["callId"])
    else:
        raise
except TelloApiConnectionError as e:
    # The call may have been placed: retry with the same key, never a new one.
    call = await api.call_drafts.confirm(draft_id, idempotency_key=e.idempotency_key)
```

## 7. Examples

Runnable programs live in [`examples/`](https://github.com/tello-ai/tello-python/blob/main/examples/README.md):

```bash
uv run python examples/basic_call.py       # connect, one call, answer each turn
uv run python examples/agent_callback.py   # full lifecycle, history, cancel, typed errors
uv run python examples/call_summary.py     # gated live scenario ending in call.summary
```

They place real calls. Read [`examples/README.md`](https://github.com/tello-ai/tello-python/blob/main/examples/README.md) first.

## 8. Version compatibility

`tello-ai-sdk 0.1.x` implements Tello WS protocol `1.0`.

The full frame contract is in [`docs/protocol/sdk-ws.v1.md`](https://github.com/tello-ai/tello-python/blob/main/docs/protocol/sdk-ws.v1.md),
with [`docs/events/sdk-events.v1.schema.json`](https://github.com/tello-ai/tello-python/blob/main/docs/events/sdk-events.v1.schema.json)
and [`docs/errors/errors.v1.json`](https://github.com/tello-ai/tello-python/blob/main/docs/errors/errors.v1.json). Those three files
are generated copies of the canonical contract that lives beside the gateway
implementation — read them here, edit them there.
