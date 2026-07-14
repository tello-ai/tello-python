# Changelog

## 0.1.0 (unreleased)

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
  `agentIdRequired` / `callIdRequired` / `callNotFound` / `callNotCompleted` /
  `smsToRequired` / `smsMessageRequired` / `smsFailed` / `callAlreadyActive` /
  `noActiveCall` / `dtmfDigitsRequired` / `dtmfDigitsInvalid` / `callRejected` /
  `internalError`.
- Added `dtmf.accepted` event parsing (`DtmfAcceptedEvent`), acking a `sendDtmf` command.
- `send_sms(to, message, request_id=None)` no longer accepts/sends `call_id`
  (the `sendSms` wire command carries only `to` / `message` / `requestId`).
- Python attribute names stay snake_case (`event.call_id`, `event.turn_index`, ...);
  `Event` gains a `session_id` attribute (parsed from `sessionId`).
- Outbound commands were already camelCase and are unchanged.
- Error-code → exception mapping; automatic pong via `websockets`.
- `TELLO_API_KEY` / `TELLO_URL` environment-variable config (`TelloClient()` with no args).
- Version sourced solely from `src/tello/_version.py` (hatch dynamic version).

### Fixes (code review)

- `wait_closed()` no longer hangs when the gateway rejects a `create_call`
  (agentIdRequired / callRejected / internalError); it raises the mapped error.
- Abnormal mid-call disconnect now raises `ConnectionClosedError` instead of
  returning as a phantom success.
- Receive loop drops valid-JSON non-object frames instead of crashing.
- Terminal handler that starts a follow-up call no longer trips a stale done flag.
- `DISCONNECTED` is delivered as a typed `Event` (was a raw dict).
- Map close code 4429 to `SessionReplacedError`; derive auth error from the
  socket close code on the connect-then-send race.
- Remove empty `calls.py` placeholder.
