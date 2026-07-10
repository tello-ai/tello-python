# Changelog

## 0.1.0 (unreleased)

- Initial WS realtime client for turn-provider-gateway `/sdk`.
- `TelloClient`: connect (Bearer auth), `create_call` / `answer` / `send_dtmf` / `cancel`, pub/sub event handlers, `wait_closed`.
- `send_dtmf(digits, message_id=None, request_id=None)`: mirrors `answer` but sends DTMF `digits` via the `sendDtmf` wire command.
- Event parsing for `user.turn` / `agent.turn` / `call.statusChanged` / `call.completed` / `call.noAnswer` / `call.failed` / `error`.

### Changed (camelCase wire contract)

- Inbound frames are camelCase-only: event types `call.statusChanged` / `call.noAnswer`,
  keys `sessionId` / `callId` / `turnIndex` / `previousStatus` / `failureReason` / `requestId`,
  status vocabulary `inProgress` / `noAnswer` (etc.), error codes `toRequired` /
  `agentIdRequired` / `callAlreadyActive` / `noActiveCall` / `callRejected` / `internalError`.
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
