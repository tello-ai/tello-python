# Changelog

## 0.1.0 (unreleased)

- Initial WS realtime client for turn-provider-gateway `/sdk`.
- `TelloClient`: connect (Bearer auth), `create_call` / `answer` / `cancel`, pub/sub event handlers, `wait_closed`.
- Event parsing for `user.turn` / `agent.turn` / `call.status_changed` / `call.completed` / `call.no_answer` / `call.failed` / `error`.
- Error-code → exception mapping; automatic pong via `websockets`.
- `TELLO_API_KEY` / `TELLO_URL` environment-variable config (`TelloClient()` with no args).
- Version sourced solely from `src/tello/_version.py` (hatch dynamic version).
