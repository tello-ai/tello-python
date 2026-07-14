"""Run a controlled call, then fetch its summary and send one follow-up SMS.

This is intentionally not a test: it creates a real call and SMS. Read
``examples/README.md`` before running it.
"""

from __future__ import annotations

import asyncio
import os
import uuid

from tello import EventType, TelloClient, TelloError


def require_environment() -> dict[str, str | float]:
    """Fail closed before constructing a client or opening a WebSocket."""
    if os.environ.get("ALLOW_LIVE_SIDE_EFFECTS") != "true":
        raise RuntimeError("set ALLOW_LIVE_SIDE_EFFECTS=true to run this live call scenario")

    required = (
        "TELLO_API_KEY",
        "TELLO_URL",
        "TELLO_AGENT_ID",
        "LIVE_CALL_TO",
        "LIVE_SMS_TO",
        "LIVE_CALL_TIMEOUT_SECONDS",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing required environment variables: {', '.join(missing)}")

    try:
        timeout_seconds = float(os.environ["LIVE_CALL_TIMEOUT_SECONDS"])
    except ValueError as exc:
        raise RuntimeError("LIVE_CALL_TIMEOUT_SECONDS must be a positive number") from exc
    if timeout_seconds <= 0:
        raise RuntimeError("LIVE_CALL_TIMEOUT_SECONDS must be a positive number")

    return {
        "api_key": os.environ["TELLO_API_KEY"],
        "url": os.environ["TELLO_URL"],
        "agent_id": os.environ["TELLO_AGENT_ID"],
        "call_to": os.environ["LIVE_CALL_TO"],
        "sms_to": os.environ["LIVE_SMS_TO"],
        "timeout_seconds": timeout_seconds,
        "prompt": os.environ.get(
            "LIVE_CALL_PROMPT",
            "Run a controlled SDK live scenario and keep the conversation brief.",
        ),
        "reply": os.environ.get(
            "LIVE_CALL_REPLY",
            "This is a controlled TPG SDK live scenario. Thank you.",
        ),
        "sms_message": os.environ.get(
            "LIVE_SMS_MESSAGE",
            "[TPG live scenario] the controlled call completed successfully.",
        ),
    }


async def wait_for_stage(stage, failed, label: str, timeout_seconds: float):
    """Wait for one correlated response, surfacing any error frame first."""
    done, _ = await asyncio.wait(
        {stage, failed}, timeout=timeout_seconds, return_when=asyncio.FIRST_COMPLETED
    )
    if not done:
        raise TimeoutError(f"timed out waiting for {label}")
    if failed.done():
        raise RuntimeError(failed.result())
    return stage.result()


async def main() -> None:
    config = require_environment()
    timeout_seconds = config["timeout_seconds"]
    assert isinstance(timeout_seconds, float)
    loop = asyncio.get_running_loop()
    completed = loop.create_future()
    call_created = loop.create_future()
    answer_accepted = loop.create_future()
    agent_turn_received = loop.create_future()
    summary_received = loop.create_future()
    sms_sent = loop.create_future()
    failed = loop.create_future()
    summary_request_id = f"live-summary-{uuid.uuid4()}"
    sms_request_id = f"live-sms-{uuid.uuid4()}"
    answer_request_id = f"live-answer-{uuid.uuid4()}"
    answer_message_id = f"live-message-{uuid.uuid4()}"
    answer_sent = False
    call_terminal = False

    def fail(message: str) -> None:
        if not failed.done():
            failed.set_result(message)

    async with TelloClient(api_key=str(config["api_key"]), url=str(config["url"])) as client:

        @client.on(EventType.CALL_CREATED)
        def on_call_created(event) -> None:
            if not call_created.done():
                print(f"[call.created] callId={event.call_id}")
                call_created.set_result(event.call_id)

        @client.on(EventType.CALL_STATUS_CHANGED)
        def on_status(event) -> None:
            nonlocal call_terminal
            print(f"[status] {event.previous_status} -> {event.status}")
            if event.status == "cancelled":
                call_terminal = True
                fail("call ended with unexpected terminal status: cancelled")

        @client.on(EventType.USER_TURN)
        async def on_user_turn(event) -> None:
            nonlocal answer_sent
            print(f"[user.turn #{event.turn_index}] {event.text}")
            if not call_created.done():
                fail("received user.turn before call.created")
                return
            if event.call_id != call_created.result():
                fail("received user.turn for a different call")
                return
            if not answer_sent:
                answer_sent = True
                await client.answer(
                    text=str(config["reply"]),
                    message_id=answer_message_id,
                    request_id=answer_request_id,
                )
                print(f"[answer] requestId={answer_request_id}")

        @client.on(EventType.ANSWER_ACCEPTED)
        def on_answer_accepted(event) -> None:
            if event.request_id != answer_request_id:
                return
            if not call_created.done():
                fail("received answer.accepted before call.created")
                return
            if event.call_id != call_created.result() or event.message_id != answer_message_id:
                fail("answer.accepted did not match the submitted answer")
                return
            if not answer_accepted.done():
                print(f"[answer.accepted] messageId={event.message_id}")
                answer_accepted.set_result(event)

        @client.on(EventType.AGENT_TURN)
        def on_agent_turn(event) -> None:
            print(f"[agent.turn #{event.turn_index}] {event.text}")
            if not call_created.done():
                fail("received agent.turn before call.created")
                return
            if (
                answer_accepted.done()
                and event.call_id == call_created.result()
                and event.text == config["reply"]
                and not agent_turn_received.done()
            ):
                agent_turn_received.set_result(event)

        @client.on(EventType.CALL_COMPLETED)
        def on_completed(event) -> None:
            nonlocal call_terminal
            call_terminal = True
            if event.status != "completed":
                fail(f"call.completed carried unexpected status: {event.status}")
            elif not answer_accepted.done() or not agent_turn_received.done():
                fail("call completed before the answer acknowledgement and agent turn")
            elif event.call_id != call_created.result():
                fail("call.completed belonged to a different call")
            elif not completed.done():
                print(f"[call.completed] callId={event.call_id}")
                completed.set_result(event.call_id)

        @client.on(EventType.CALL_NO_ANSWER)
        def on_no_answer(event) -> None:
            nonlocal call_terminal
            call_terminal = True
            fail(f"call ended with noAnswer: {event.failure_reason or 'no reason supplied'}")

        @client.on(EventType.CALL_FAILED)
        def on_call_failed(event) -> None:
            nonlocal call_terminal
            call_terminal = True
            fail(f"call failed: {event.failure_reason or 'no reason supplied'}")

        @client.on(EventType.CALL_SUMMARY)
        def on_summary(event) -> None:
            if event.request_id == summary_request_id and not summary_received.done():
                print(f"[call.summary] callId={event.call_id} status={event.status}")
                summary_received.set_result(event)

        @client.on(EventType.SMS_SENT)
        def on_sms_sent(event) -> None:
            if event.request_id == sms_request_id and not sms_sent.done():
                print(f"[sms.sent] id={event.sms_id} status={event.status} to={event.to}")
                sms_sent.set_result(event)

        @client.on(EventType.ERROR)
        def on_error(event) -> None:
            fail(f"gateway error {event.code}: {event.message}")

        @client.on(EventType.DISCONNECTED)
        def on_disconnected(_event) -> None:
            fail("gateway disconnected before scenario completed")

        print(f"[createCall] to={config['call_to']} agentId={config['agent_id']}")
        await client.create_call(
            to=str(config["call_to"]),
            agent_id=str(config["agent_id"]),
            prompt=str(config["prompt"]),
            metadata={"source": "tello-python-call-summary-sms-example"},
        )
        try:
            await wait_for_stage(call_created, failed, "call.created", timeout_seconds)
            await wait_for_stage(answer_accepted, failed, "answer.accepted", timeout_seconds)
            await wait_for_stage(agent_turn_received, failed, "agent.turn", timeout_seconds)
            call_id = await wait_for_stage(completed, failed, "call.completed", timeout_seconds)
        except TimeoutError:
            if not call_terminal:
                print("[timeout] attempting to cancel the active call")
                try:
                    await client.cancel()
                except TelloError as exc:
                    print(f"[cancel] failed: {exc}")
            raise

        print(f"[getSummary] requestId={summary_request_id}")
        await client.get_summary(call_id=call_id, request_id=summary_request_id)
        summary = await wait_for_stage(
            summary_received, failed, "call.summary", timeout_seconds
        )
        if summary.call_id != call_id or summary.status != "completed":
            raise RuntimeError("call.summary did not confirm the completed call")

        print(f"[sendSms] requestId={sms_request_id} to={config['sms_to']}")
        await client.send_sms(
            to=str(config["sms_to"]),
            message=str(config["sms_message"]),
            request_id=sms_request_id,
        )
        await wait_for_stage(sms_sent, failed, "sms.sent", timeout_seconds)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (RuntimeError, TimeoutError, TelloError) as exc:
        raise SystemExit(f"live call-summary-SMS scenario failed: {exc}") from exc
