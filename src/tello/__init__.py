"""Tello SDK for Python — WebSocket realtime client for turn-provider-gateway.

    import asyncio
    from tello import TelloClient, EventType

    async def main():
        async with TelloClient(api_key="tello_live_xxx", url="wss://api.telloai.io/sdk") as client:
            @client.on(EventType.USER_TURN)
            async def on_user_turn(event):
                await client.answer(text="확인했습니다.")

            await client.create_call(to="+821012345678", prompt="예약 확인")
            await client.wait_closed()

    asyncio.run(main())
"""

from ._version import __version__
from .client import TelloClient
from .config import DEFAULT_URL, ClientConfig
from .errors import (
    AuthenticationError,
    CallAlreadyActiveError,
    CallProviderError,
    CallRefusedError,
    CallRejectedError,
    ConnectionClosedError,
    NoActiveCallError,
    SessionReplacedError,
    TelloError,
    TelloServerError,
    ValidationError,
)
from .events import (
    AnswerAcceptedEvent,
    CallCreatedEvent,
    CallSummaryEvent,
    DtmfAcceptedEvent,
    ErrorEvent,
    Event,
    EventType,
    StatusChangedEvent,
    TerminalEvent,
    TurnEvent,
    is_terminal,
    parse_event,
)
from .types import PROTOCOL_VERSION, PublicStatus

__all__ = [
    "__version__",
    "TelloClient",
    "ClientConfig",
    "DEFAULT_URL",
    "EventType",
    "Event",
    "CallCreatedEvent",
    "AnswerAcceptedEvent",
    "DtmfAcceptedEvent",
    "CallSummaryEvent",
    "TurnEvent",
    "StatusChangedEvent",
    "TerminalEvent",
    "ErrorEvent",
    "parse_event",
    "is_terminal",
    "PublicStatus",
    "PROTOCOL_VERSION",
    "TelloError",
    "ConnectionClosedError",
    "AuthenticationError",
    "ValidationError",
    "CallAlreadyActiveError",
    "NoActiveCallError",
    "CallRejectedError",
    "CallRefusedError",
    "CallProviderError",
    "SessionReplacedError",
    "TelloServerError",
]
