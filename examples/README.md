# Live scenario examples

These programs make real calls. They are deliberately outside `pytest` and must
only be run against controlled test recipients.

Every execution requires this explicit acknowledgement:

```sh
export ALLOW_LIVE_SIDE_EFFECTS=true
```

The scripts check that gate and all required configuration before constructing a
`TelloClient` or opening a WebSocket. They never retry a call command.

Copy the template, replace placeholders only with controlled test recipients,
review the values, and explicitly enable the gate before sourcing it:

```sh
cp examples/.env.example examples/.env
# Edit examples/.env: replace placeholders, then set ALLOW_LIVE_SIDE_EFFECTS=true.
set -a
. examples/.env
set +a
```

`examples/.env` contains credentials and must remain local.

## Shared configuration

The template contains these values. You may instead set them directly in your
shell; do not commit credentials or real recipient numbers.

```sh
export TELLO_API_KEY='tello_live_...'
export TELLO_URL='wss://your-staging-gateway.example/sdk'
export LIVE_CALL_TO='+8210...controlled-test-recipient'
export LIVE_CALL_TIMEOUT_SECONDS=120
export ALLOW_LIVE_SIDE_EFFECTS=true
```

For the call flow, `LIVE_CALL_PROMPT` and `LIVE_CALL_REPLY` are optional; the
defaults are deterministic, clearly marked test text.

## Completed call → summary

This starts one controlled outbound call, waits for `call.created`, answers its
first `user.turn` with a request ID, then requires the matching
`answer.accepted` and resulting `agent.turn`. Only after those observations and
`call.completed` does it request the correlated `call.summary`.

```sh
uv run python examples/call_summary.py
```

In addition to the shared gate, this scenario requires `TELLO_API_KEY`,
`TELLO_URL`, `LIVE_CALL_TO`, and `LIVE_CALL_TIMEOUT_SECONDS`.

`call.noAnswer`, `call.failed`, `call.statusChanged: cancelled`, gateway error
frames, and disconnects fail the scenario. If the active call does not reach a
terminal event before `LIVE_CALL_TIMEOUT_SECONDS`, the script attempts one
`cancel` command and exits with an error. It does not send a summary request
after any non-completed terminal state.
