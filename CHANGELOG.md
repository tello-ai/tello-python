# Changelog

## 0.1.1 (2026-09-30)

### Changed

- **Behavior change**: the default URL is now `wss://api.telloai.io/sdk`, the
  production gateway (was `ws://localhost:3000/sdk`). The old default, also
  used by the README examples, pointed at a local development gateway, so a
  client that relied on it or followed the README could not connect. Pass
  `url=` or set `TELLO_URL` to reach another gateway.

## 0.1.0 (2026-09-30)

### Fixed

- `wait_closed()` no longer ends on an error from a command other than
  `create_call`. It used to raise on any error frame that arrived while a call
  was active, so a mid-call `dtmfDigitsInvalid` raised `ValidationError` while
  the call was still live, and a caller that then closed the socket made the
  gateway cancel the real call. The wire contract (§6) keeps the connection
  open on a failed command, and a failed `answer` / `send_dtmf` /
  `get_summary` / `cancel` leaves the call running, so `wait_closed()` now
  raises only for an error echoing the `requestId` of the current call's
  `create_call`: a refusal, or a failure after `call.created`. Errors from
  those other commands are delivered only to `EventType.ERROR` handlers.
- `create_call` always sends a `requestId`: `request_id` when non-empty,
  otherwise a generated UUID. The signature is unchanged.
- A `callAlreadyActive` answering the `create_call` that started the call now
  ends `wait_closed()` with `CallAlreadyActiveError`. Right after a call ends,
  the gateway holds the session until it has cleaned that call up (contract
  §4.1), so a `create_call` sent in that window is refused and never gets
  `call.created`; `wait_closed()` used to ignore that refusal and hang. Retry
  the call shortly. A `callAlreadyActive` answering a `create_call` sent
  during a live call is still only an event, and `noActiveCall` never ends
  the wait.
- A `create_call` whose frame cannot be sent (the client is not connected, or
  the socket has already closed) no longer leaves the client treating a call
  as running. It raises as before, the next `wait_closed()` raises the same
  error instead of hanging, and the next `create_call` starts a new call.
- A call cut off by a dropped connection no longer carries over into the next
  connection: after `connect()`, an error echoing the dropped call's
  `create_call` requestId no longer ends the new call's wait.
- Reconnecting from a `DISCONNECTED` handler works. The dropped connection's
  receive loop marked the new connection closed once the handler returned,
  so `wait_closed()` returned at once while the new call was still live, and
  the dropped call's wait returned instead of raising `ConnectionClosedError`.

### Changed (call wait)

- **Behavior change**: a `wait_closed()` started during a call returns when
  that call ends, with that call's outcome, even if a handler has already
  started the next call. It used to keep waiting through a follow-up call
  started from a terminal handler. Call `wait_closed()` again to wait for the
  follow-up.

### Changed (packaging)

- Requires `websockets>=14` (was `>=13`). The test suite runs on the asyncio
  implementation that `websockets` 14 made the default, so 13 was declared
  but never tested.
- The package metadata declares the license as a PEP 639 expression
  (`License-Expression: Apache-2.0`, with `LICENSE` as the license file) and
  lists trove classifiers for Python 3.10–3.13, `Typing :: Typed`,
  `Framework :: AsyncIO`, and `Development Status :: 3 - Alpha`. Building
  needs hatchling 1.27 or newer.
- The README links on PyPI point at GitHub; as relative paths they were
  broken on the project page.

### Breaking changes (PyPI distribution name)

- **Breaking**: the distribution is published as `tello-ai-sdk`. `tello-sdk` on PyPI belongs to an unrelated Tello EDU drone library, so `pip install tello-sdk` never installed this SDK. The import name stays `tello`.
- License is Apache-2.0 (was MIT), matching tello-go and tello-js.

### Breaking changes (SMS removed from the SDK contract)

- **Breaking**: `send_sms` was removed entirely (the `sendSms` command, the `sms.sent` event, and the `SmsSentEvent` / `EventType.SMS_SENT` symbols no longer exist). The gateway dropped the `sendSms` handler, so a client still sending the frame matches no handler, receives no response at all, and blocks until its own timeout.
- **Breaking**: the `smsToRequired` / `smsMessageRequired` / `smsFailed` error codes are gone from the contract and from the error-code → exception mapping.
- **Breaking**: `examples/send_sms.py` was deleted, and `examples/call_summary_sms.py` became `examples/call_summary.py` (the call → `getSummary` half is unchanged; only the follow-up SMS was dropped). `LIVE_SMS_TO` / `LIVE_SMS_MESSAGE` are no longer read by any example.

### Breaking changes (agent selection removed from the SDK contract)

- **Breaking**: `create_call` no longer takes an `agent_id` parameter; the `createCall` wire frame never carries an `agentId` field (the gateway resolves the agent server-side). The `agentIdRequired` error code is gone from the contract.
- **Breaking**: `list_agents` was removed entirely (the `listAgents` command, the `agents.listed` event, and the `AgentInfo` / `AgentsListedEvent` / `EventType.AGENTS_LISTED` symbols no longer exist).

- Initial WS realtime client for turn-provider-gateway `/sdk`.
- `TelloClient`: connect (internal `auth`/`auth.ok` handshake), `create_call` / `answer` / `send_dtmf` / `cancel`, pub/sub event handlers, `wait_closed`.
- `send_dtmf(digits, message_id=None, request_id=None)`: mirrors `answer` but sends DTMF `digits` via the `sendDtmf` wire command.
- Event parsing for `user.turn` / `agent.turn` / `call.statusChanged` / `call.completed` / `call.noAnswer` / `call.failed` / `error`.

### Changed (auth handshake)

- Connection auth moved from the `Authorization: Bearer` upgrade header to an
  application-level handshake: the client sends
  `{"event":"auth","data":{"token":"<apiKey>"}}` as the first frame and blocks
  until the server returns `auth.ok` before `connect()` succeeds. Auth stays
  internal (no public step). The API key never appears on the upgrade request,
  in the URL query, in logs, or in exceptions. An `unauthenticated` error frame,
  a 4401 close, or an `auth.ok` wait timeout each raise `AuthenticationError`
  from `connect()`.

### Changed (camelCase wire contract)

- Inbound frames are camelCase-only: event types `call.statusChanged` / `call.noAnswer`,
  keys `sessionId` / `callId` / `turnIndex` / `previousStatus` / `failureReason` / `requestId`,
  status vocabulary `inProgress` / `noAnswer` (etc.), error codes `toRequired` /
  `callIdRequired` / `callNotFound` / `callNotCompleted` / `callAlreadyActive` /
  `noActiveCall` / `dtmfDigitsRequired` / `dtmfDigitsInvalid` / `callRejected` /
  `internalError`.
- Added `dtmf.accepted` event parsing (`DtmfAcceptedEvent`), acking a `sendDtmf` command.
- Python attribute names stay snake_case (`event.call_id`, `event.turn_index`, ...);
  `Event` gains a `session_id` attribute (parsed from `sessionId`).
- Outbound commands were already camelCase and are unchanged.
- Error-code → exception mapping; automatic pong via `websockets`.
- `TELLO_API_KEY` / `TELLO_URL` environment-variable config (`TelloClient()` with no args).
- Version sourced solely from `src/tello/_version.py` (hatch dynamic version).

### Fixes (code review)

- `wait_closed()` no longer hangs when the gateway rejects a `create_call`
  (toRequired / callRejected / internalError); it raises the mapped error.
- Abnormal mid-call disconnect now raises `ConnectionClosedError` instead of
  returning as a phantom success.
- Receive loop drops valid-JSON non-object frames instead of crashing.
- Terminal handler that starts a follow-up call no longer trips a stale done flag.
- `DISCONNECTED` is delivered as a typed `Event` (was a raw dict).
- Map close code 4429 to `SessionReplacedError`; derive auth error from the
  socket close code on the connect-then-send race.
- Remove empty `calls.py` placeholder.
