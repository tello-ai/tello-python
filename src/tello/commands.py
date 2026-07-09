"""Outbound command frame builders.

Client -> server frames use the ``@nestjs/platform-ws`` routing envelope
``{"event": "<command>", "data": {...}}``. This asymmetry (enveloped outbound,
flat inbound) is intentional; keep it isolated here. See
``contracts/protocol/sdk-ws.v1.md`` §3-4.
"""

from __future__ import annotations

import json
from typing import Any


def create_call_frame(
    to: str,
    agent_id: str,
    prompt: str = "",
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"to": to, "agentId": agent_id, "prompt": prompt}
    if metadata is not None:
        data["metadata"] = metadata
    if request_id is not None:
        data["requestId"] = request_id
    return {"event": "create_call", "data": data}


def answer_frame(
    text: str = "",
    message_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"text": text}
    if message_id is not None:
        data["messageId"] = message_id
    if request_id is not None:
        data["requestId"] = request_id
    return {"event": "answer", "data": data}


def cancel_frame() -> dict[str, Any]:
    return {"event": "cancel", "data": {}}


def encode(frame: dict[str, Any]) -> str:
    return json.dumps(frame)
