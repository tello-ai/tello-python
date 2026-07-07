# Changelog

## 0.1.0 (unreleased)

- Initial WS realtime client for turn-provider-gateway `/sdk`.
- `TelloClient`: connect (Bearer auth), `create_call` / `answer` / `cancel`, pub/sub event handlers, `wait_closed`.
- Event parsing for `user.turn` / `agent.turn` / `call.status_changed` / `call.completed` / `call.no_answer` / `call.failed` / `error`.
- Error-code → exception mapping; automatic pong via `websockets`.
- `TELLO_API_KEY` / `TELLO_URL` environment-variable config (`TelloClient()` with no args).
- Version sourced solely from `src/tello/_version.py` (hatch dynamic version).

### Fixes (code review)

- `wait_closed()` no longer hangs when the gateway rejects a `create_call`
  (agent_id_required / call_rejected / internal_error); it raises the mapped error.
- Abnormal mid-call disconnect now raises `ConnectionClosedError` instead of
  returning as a phantom success.
- Receive loop drops valid-JSON non-object frames instead of crashing.
- Terminal handler that starts a follow-up call no longer trips a stale done flag.
- `DISCONNECTED` is delivered as a typed `Event` (was a raw dict).
- Map close code 4429 to `SessionReplacedError`; derive auth error from the
  socket close code on the connect-then-send race.
- Remove empty `calls.py` placeholder.
