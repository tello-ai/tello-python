# Live scenario examples

These programs make real calls and send real SMS messages. They are deliberately
outside `pytest` and must only be run against controlled test recipients.

Every execution requires this explicit acknowledgement:

```sh
export ALLOW_LIVE_SIDE_EFFECTS=true
```

The scripts check that gate and all required configuration before constructing a
`TelloClient` or opening a WebSocket. They never retry a call or SMS command.

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
export TELLO_AGENT_ID='your-published-agent-id'
export LIVE_SMS_TO='+8210...controlled-test-recipient'
export LIVE_CALL_TO='+8210...controlled-test-recipient'
export LIVE_CALL_TIMEOUT_SECONDS=120
export ALLOW_LIVE_SIDE_EFFECTS=true
```

`LIVE_SMS_MESSAGE` is optional and defaults to a clearly marked test message.
For the call flow, `LIVE_CALL_PROMPT` and `LIVE_CALL_REPLY` are optional; the
defaults are deterministic, clearly marked test text.

## SMS only

This sends exactly one SMS and waits for the correlated `sms.sent` event.

```sh
uv run python examples/send_sms.py
```

The required values are `TELLO_API_KEY`, `TELLO_URL`, `LIVE_SMS_TO`, and the
live-side-effect gate.

## Completed call → summary → SMS

This starts one controlled outbound call, waits for `call.created`, answers its
first `user.turn` with a request ID, then requires the matching
`answer.accepted` and resulting `agent.turn`. Only after those observations and
`call.completed` does it request the correlated `call.summary`, send one
follow-up SMS, and wait for its correlated `sms.sent` event.

```sh
uv run python examples/call_summary_sms.py
```

In addition to the shared gate, this scenario requires `TELLO_API_KEY`,
`TELLO_URL`, `TELLO_AGENT_ID`, `LIVE_CALL_TO`, `LIVE_SMS_TO`, and
`LIVE_CALL_TIMEOUT_SECONDS`.

`call.noAnswer`, `call.failed`, `call.statusChanged: cancelled`, gateway error
frames, and disconnects fail the scenario. If the active call does not reach a
terminal event before `LIVE_CALL_TIMEOUT_SECONDS`, the script attempts one
`cancel` command and exits with an error. It does not send a summary request or
SMS after any non-completed terminal state.
