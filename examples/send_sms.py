"""Send one SMS to a controlled recipient through the live Tello gateway.

This is intentionally not a test: it has a real-world side effect. Read
``examples/README.md`` before running it.
"""

from __future__ import annotations

import asyncio
import os
import uuid

from tello import EventType, TelloClient


def require_environment() -> dict[str, str]:
    """Fail closed before constructing a client or opening a WebSocket."""
    if os.environ.get("ALLOW_LIVE_SIDE_EFFECTS") != "true":
        raise RuntimeError("set ALLOW_LIVE_SIDE_EFFECTS=true to run this live SMS scenario")

    required = ("TELLO_API_KEY", "TELLO_URL", "LIVE_SMS_TO")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing required environment variables: {', '.join(missing)}")

    return {
        "api_key": os.environ["TELLO_API_KEY"],
        "url": os.environ["TELLO_URL"],
        "sms_to": os.environ["LIVE_SMS_TO"],
        "sms_message": os.environ.get(
            "LIVE_SMS_MESSAGE", "[TPG live scenario] controlled-recipient SMS check"
        ),
    }


async def main() -> None:
    config = require_environment()
    request_id = f"live-sms-{uuid.uuid4()}"
    sms_sent = asyncio.get_running_loop().create_future()
    failed = asyncio.get_running_loop().create_future()

    async with TelloClient(api_key=config["api_key"], url=config["url"]) as client:

        @client.on(EventType.SMS_SENT)
        def on_sms_sent(event) -> None:
            if event.request_id == request_id and not sms_sent.done():
                print(f"[sms.sent] id={event.sms_id} status={event.status} to={event.to}")
                sms_sent.set_result(event)

        @client.on(EventType.ERROR)
        def on_error(event) -> None:
            if not failed.done():
                failed.set_result(f"gateway error {event.code}: {event.message}")

        @client.on(EventType.DISCONNECTED)
        def on_disconnected(_event) -> None:
            if not sms_sent.done() and not failed.done():
                failed.set_result("gateway disconnected before sms.sent")

        print(f"[sendSms] requestId={request_id} to={config['sms_to']}")
        await client.send_sms(
            to=config["sms_to"],
            message=config["sms_message"],
            request_id=request_id,
        )
        done, _ = await asyncio.wait(
            {sms_sent, failed}, timeout=30, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            raise TimeoutError("timed out waiting for sms.sent")
        if failed.done():
            raise RuntimeError(failed.result())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (RuntimeError, TimeoutError) as exc:
        raise SystemExit(f"live SMS scenario failed: {exc}") from exc
