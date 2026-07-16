"""Advanced example: an agent that holds a conversation over a live call.

Shows the full lifecycle and every inbound event:

* explicit ``connect()`` / ``aclose()`` (``TelloClient(...)`` == ``new TelloClient``)
* per-turn response generation with conversation history
* answering `user.turn`, observing `agent.turn` / `call.statusChanged`
* all terminal states (`completed` / `noAnswer` / `failed`) and `error`
* ending the call early with `cancel()` on an intent keyword
* mapping error frames / auth failure to exceptions

Run against a locally-running turn-provider-gateway:

    TELLO_API_KEY=tello_live_xxx TELLO_URL=ws://localhost:3000/sdk \
        python examples/agent_callback.py
"""

from __future__ import annotations

import asyncio
import os

from tello import (
    AuthenticationError,
    EventType,
    TelloClient,
    TelloError,
)


class Agent:
    """Toy conversation brain. Replace ``respond`` with your own LLM / rules."""

    #: keywords that end the call
    HANGUP_HINTS = ("괜찮습니다", "감사합니다", "그만", "bye")

    def __init__(self) -> None:
        # (role, text) history the way your own model would consume it
        self.history: list[tuple[str, str]] = []

    def respond(self, text: str) -> str:
        self.history.append(("user", text))
        reply = self._generate(text)
        self.history.append(("assistant", reply))
        return reply

    def wants_hangup(self, text: str) -> bool:
        return any(hint in text for hint in self.HANGUP_HINTS)

    def _generate(self, text: str) -> str:
        # Stand-in for real inference. Deterministic so the example is testable.
        if "예약" in text:
            return "네, 예약 도와드리겠습니다. 원하시는 날짜를 말씀해 주세요."
        if any(ch.isdigit() for ch in text):
            return "확인했습니다. 해당 시간으로 예약을 진행할까요?"
        return "말씀 감사합니다. 좀 더 자세히 알려주시겠어요?"


async def run(agent: Agent, client: TelloClient) -> None:
    @client.on(EventType.CALL_STATUS_CHANGED)
    def on_status(event) -> None:
        print(f"[status] {event.previous_status} -> {event.status}")

    @client.on(EventType.USER_TURN)
    async def on_user_turn(event) -> None:
        print(f"[user #{event.turn_index}] {event.text}")
        if agent.wants_hangup(event.text):
            print("[agent] hangup intent -> cancel")
            await client.cancel()
            return
        reply = agent.respond(event.text)
        await client.answer(text=reply)

    @client.on(EventType.AGENT_TURN)
    def on_agent_turn(event) -> None:
        # Confirmation that our answer was accepted into the call.
        print(f"[agent #{event.turn_index}] {event.text}")

    @client.on(EventType.CALL_NO_ANSWER)
    def on_no_answer(event) -> None:
        print(f"[noAnswer] reason={event.failure_reason}")

    @client.on(EventType.CALL_FAILED)
    def on_failed(event) -> None:
        print(f"[failed] reason={event.failure_reason}")

    @client.on(EventType.CALL_COMPLETED)
    def on_completed(event) -> None:
        print(f"[completed] {event.call_id} ({len(agent.history)} turns)")

    @client.on(EventType.ERROR)
    def on_error(event) -> None:
        # Non-fatal command errors arrive here without closing the socket.
        note = f" ({event.question})" if event.question else ""
        print(f"[error] {event.code}: {event.message}{note}")

    @client.on(EventType.DISCONNECTED)
    def on_disconnected(_event) -> None:
        # No auto-reconnect: the gateway has no resume protocol. Restart the
        # call on a fresh connection if you need to continue.
        print("[disconnected]")

    await client.create_call(
        to="+821012345678",
        prompt="예약 확인 전화",
        metadata={"source": "agent_callback_example"},
    )
    # Bound the demo so it can't hang forever if the call never terminates.
    try:
        await asyncio.wait_for(client.wait_closed(), timeout=120)
    except asyncio.TimeoutError:
        print("[timeout] cancelling call")
        await client.cancel()


async def main() -> None:
    api_key = os.environ.get("TELLO_API_KEY", "tello_live_xxx")
    url = os.environ.get("TELLO_URL", "ws://localhost:3000/sdk")

    agent = Agent()
    client = TelloClient(api_key=api_key, url=url)  # == new TelloClient(...)
    await client.connect()
    try:
        await run(agent, client)
    except AuthenticationError:
        print("auth failed: check TELLO_API_KEY")
    except TelloError as exc:
        print(f"tello error: {exc}")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
