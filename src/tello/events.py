"""Inbound event frames and their parser.

Gateway -> client frames are **flat** (no ``{event, data}`` envelope) and are
dispatched on the ``type`` field. Wire keys are camelCase (``callId``,
``turnIndex``, ...); the parsed Python attributes stay snake_case. See
``contracts/protocol/sdk-ws.v1.md`` and
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
    AGENTS_LISTED = "agents.listed"
    CALL_SUMMARY = "call.summary"
    SMS_SENT = "sms.sent"
    ANSWER_ACCEPTED = "answer.accepted"
    CALL_CREATED = "call.created"
    CALL_STATUS_CHANGED = "call.statusChanged"
    CALL_COMPLETED = "call.completed"
    CALL_NO_ANSWER = "call.noAnswer"
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
    session_id: str
    call_id: str
    timestamp: str
    raw: dict[str, Any]


@dataclass
class CallCreatedEvent(Event):
    """``call.created``, emitted before the first lifecycle event."""


@dataclass
class AnswerAcceptedEvent(Event):
    """``answer.accepted``, acknowledging a submitted answer command."""

    request_id: str | None
    message_id: str


@dataclass
class TurnEvent(Event):
    """``user.turn`` / ``agent.turn``."""

    turn_index: int
    text: str


@dataclass
class StatusChangedEvent(Event):
    """``call.statusChanged`` (also carries the ``cancelled`` terminal status)."""

    status: str
    previous_status: str


@dataclass
class TerminalEvent(Event):
    """``call.completed`` / ``call.noAnswer`` / ``call.failed``."""

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


@dataclass
class AgentInfo:
    """One callable agent returned by ``agents.listed``."""

    agent_id: str
    name: str
    role: str
    is_default: bool
    status: str


@dataclass
class AgentsListedEvent:
    """``agents.listed``, emitted in response to ``listAgents``."""

    type: str
    version: str
    agents: list[AgentInfo]
    raw: dict[str, Any]
    request_id: str | None = None


@dataclass
class CallSummaryEvent:
    """``call.summary``, emitted in response to ``getSummary``."""

    type: str
    version: str
    call_id: str
    status: str
    duration_seconds: int | None
    transcript: str | None
    summary: str | None
    credit_charged: int | None
    raw: dict[str, Any]
    request_id: str | None = None


@dataclass
class SmsSentEvent:
    """``sms.sent``, emitted in response to ``sendSms``."""

    type: str
    version: str
    sms_id: str
    status: str
    to: str
    message_preview: str
    raw: dict[str, Any]
    request_id: str | None = None
    call_id: str | None = None


def parse_event(
    frame: dict[str, Any],
) -> Event | ErrorEvent | AgentsListedEvent | CallSummaryEvent | SmsSentEvent | AnswerAcceptedEvent:
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
            request_id=frame.get("requestId"),
            question=frame.get("question"),
            raw=frame,
        )

    if frame_type == EventType.AGENTS_LISTED:
        return AgentsListedEvent(
            type=frame_type,
            version=frame.get("version", ""),
            request_id=frame.get("requestId"),
            agents=_agents(frame.get("agents")),
            raw=frame,
        )

    if frame_type == EventType.CALL_SUMMARY:
        return CallSummaryEvent(
            type=frame_type,
            version=frame.get("version", ""),
            request_id=frame.get("requestId"),
            call_id=frame.get("callId", ""),
            status=frame.get("status", ""),
            duration_seconds=frame.get("durationSeconds"),
            transcript=frame.get("transcript"),
            summary=frame.get("summary"),
            credit_charged=frame.get("creditCharged"),
            raw=frame,
        )

    if frame_type == EventType.SMS_SENT:
        return SmsSentEvent(
            type=frame_type,
            version=frame.get("version", ""),
            request_id=frame.get("requestId"),
            sms_id=frame.get("smsId", ""),
            status=frame.get("status", ""),
            to=frame.get("to", ""),
            message_preview=frame.get("messagePreview", ""),
            call_id=frame.get("callId"),
            raw=frame,
        )

    base = {
        "type": frame_type,
        "version": frame.get("version", ""),
        "session_id": frame.get("sessionId", ""),
        "call_id": frame.get("callId", ""),
        "timestamp": frame.get("timestamp", ""),
        "raw": frame,
    }

    if frame_type == EventType.CALL_CREATED:
        return CallCreatedEvent(**base)

    if frame_type == EventType.ANSWER_ACCEPTED:
        return AnswerAcceptedEvent(
            **base,
            request_id=frame.get("requestId"),
            message_id=frame.get("messageId", ""),
        )

    if frame_type in (EventType.USER_TURN, EventType.AGENT_TURN):
        return TurnEvent(**base, turn_index=frame.get("turnIndex", 0), text=frame.get("text", ""))

    if frame_type == EventType.CALL_STATUS_CHANGED:
        return StatusChangedEvent(
            **base,
            status=frame.get("status", ""),
            previous_status=frame.get("previousStatus", ""),
        )

    if frame_type in _TERMINAL_TYPES:
        return TerminalEvent(
            **base,
            status=frame.get("status", ""),
            failure_reason=frame.get("failureReason"),
        )

    return Event(**base)


def _agents(value: Any) -> list[AgentInfo]:
    if not isinstance(value, list):
        return []
    agents = []
    for row in value:
        if not isinstance(row, dict):
            continue
        agents.append(
            AgentInfo(
                agent_id=row.get("agentId", ""),
                name=row.get("name", ""),
                role=row.get("role", ""),
                is_default=row.get("isDefault") is True,
                status=row.get("status", ""),
            )
        )
    return agents


def is_terminal(event: Event) -> bool:
    """True if ``event`` ends the current call.

    Terminal set = the three ``call.*`` terminals plus a ``call.statusChanged``
    with status ``cancelled`` (how the gateway signals a cancelled call).
    """
    if event.type in _TERMINAL_TYPES:
        return True
    return (
        event.type == EventType.CALL_STATUS_CHANGED
        and getattr(event, "status", None) == "cancelled"
    )
