# Changelog

## 0.1.0 (unreleased)

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
