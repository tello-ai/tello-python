"""Shared value types for the Tello SDK.

Mirrors the public status vocabulary from the gateway WS contract
(``contracts/protocol/sdk-ws.v1.md`` / gateway ``sdk-events.ts``).
"""

from __future__ import annotations

from enum import Enum


class PublicStatus(str, Enum):
    """Public call status vocabulary sent by the gateway."""

    QUEUED = "queued"
    DIALING = "dialing"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    TRANSFERRING = "transferring"
    COMPLETED = "completed"
    NO_ANSWER = "no_answer"
    FAILED = "failed"
    CANCELLED = "cancelled"


PROTOCOL_VERSION = "1.0"
