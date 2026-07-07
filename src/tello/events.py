"""Inbound event frames and their parser.

Gateway -> client frames are **flat** (no ``{event, data}`` envelope) and are
dispatched on the ``type`` field. See ``contracts/protocol/sdk-ws.v1.md`` and
``contracts/events/sdk-events.v1.schema.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class EventType:
    """String constants for inbound event ``type`` values.

    The first group matches the gateway 1:1. ``DISCONNECTED`` is an SDK-local
    pseudo-event emitted when the WS connection ends (never sent by the gateway).
    """

    USER_TURN = "user.turn"
    AGENT_TURN = "agent.turn"
    CALL_STATUS_CHANGED = "call.status_changed"
    CALL_COMPLETED = "call.completed"
    CALL_NO_ANSWER = "call.no_answer"
    CALL_FAILED = "call.failed"
    ERROR = "error"
    DISCONNECTED = "disconnected"


_TERMINAL_TYPES = frozenset(
    {EventType.CALL_COMPLETED, EventType.CALL_NO_ANSWER, EventType.CALL_FAILED}
)


@dataclass
class Event:
    """Base inbound event. ``raw`` holds the original decoded frame."""

    type: str
    version: str
    call_id: str
    timestamp: str
    raw: dict[str, Any]


@dataclass
class TurnEvent(Event):
    """``user.turn`` / ``agent.turn``."""

    turn_index: int
    text: str


@dataclass
class StatusChangedEvent(Event):
    """``call.status_changed`` (also carries the ``cancelled`` terminal status)."""

    status: str
    previous_status: str


@dataclass
class TerminalEvent(Event):
    """``call.completed`` / ``call.no_answer`` / ``call.failed``."""

    status: str
    failure_reason: str | None = None


@dataclass
class ErrorEvent:
    """A gateway ``error`` frame (flat, not enveloped)."""

    type: str
    version: str
    code: str
    message: str
    raw: dict[str, Any]
    request_id: str | None = None
    question: str | None = None


def parse_event(frame: dict[str, Any]) -> Event | ErrorEvent:
    """Parse a decoded inbound frame into a typed event.

    Unknown ``type`` values fall back to the base :class:`Event` so forward-
    compatible additions are still delivered to subscribers.
    """
    frame_type = frame.get("type", "")

    if frame_type == EventType.ERROR:
        return ErrorEvent(
            type=frame_type,
            version=frame.get("version", ""),
            code=frame.get("code", ""),
            message=frame.get("message", ""),
            request_id=frame.get("request_id"),
            question=frame.get("question"),
            raw=frame,
        )

    base = {
        "type": frame_type,
        "version": frame.get("version", ""),
        "call_id": frame.get("call_id", ""),
        "timestamp": frame.get("timestamp", ""),
        "raw": frame,
    }

    if frame_type in (EventType.USER_TURN, EventType.AGENT_TURN):
        return TurnEvent(**base, turn_index=frame.get("turn_index", 0), text=frame.get("text", ""))

    if frame_type == EventType.CALL_STATUS_CHANGED:
        return StatusChangedEvent(
            **base,
            status=frame.get("status", ""),
            previous_status=frame.get("previous_status", ""),
        )

    if frame_type in _TERMINAL_TYPES:
        return TerminalEvent(
            **base,
            status=frame.get("status", ""),
            failure_reason=frame.get("failure_reason"),
        )

    return Event(**base)


def is_terminal(event: Event) -> bool:
    """True if ``event`` ends the current call.

    Terminal set = the three ``call.*`` terminals plus a ``call.status_changed``
    with status ``cancelled`` (how the gateway signals a cancelled call).
    """
    if event.type in _TERMINAL_TYPES:
        return True
    return (
        event.type == EventType.CALL_STATUS_CHANGED
        and getattr(event, "status", None) == "cancelled"
    )
