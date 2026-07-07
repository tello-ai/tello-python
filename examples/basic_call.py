"""Minimal end-to-end example: connect, start a call, answer each user turn.

Run against a locally-running turn-provider-gateway:

    TELLO_API_KEY=tello_live_xxx TELLO_URL=ws://localhost:3000/sdk \
        python examples/basic_call.py
"""

import asyncio
import os

from tello import EventType, TelloClient


async def main() -> None:
    api_key = os.environ.get("TELLO_API_KEY", "tello_live_xxx")
    url = os.environ.get("TELLO_URL", "ws://localhost:3000/sdk")

    async with TelloClient(api_key=api_key, url=url) as client:

        @client.on(EventType.USER_TURN)
        async def on_user_turn(event):
            print(f"[user #{event.turn_index}] {event.text}")
            await client.answer(text="확인했습니다. 계속 말씀해주세요.")

        @client.on(EventType.CALL_STATUS_CHANGED)
        async def on_status(event):
            print(f"[status] {event.previous_status} -> {event.status}")

        @client.on(EventType.CALL_COMPLETED)
        async def on_completed(event):
            print(f"[completed] {event.call_id}")

        @client.on(EventType.ERROR)
        async def on_error(event):
            print(f"[error] {event.code}: {event.message}")

        await client.create_call(agent_id="agent-1", prompt="예약 확인")
        await client.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
