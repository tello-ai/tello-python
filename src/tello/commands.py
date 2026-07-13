"""Outbound command frame builders.

Client -> server frames use the ``@nestjs/platform-ws`` routing envelope
``{"event": "<command>", "data": {...}}``. This asymmetry (enveloped outbound,
flat inbound) is intentional; keep it isolated here. See
``contracts/protocol/sdk-ws.v1.md`` §3-4.
"""

from __future__ import annotations

import json
from typing import Any


def authenticate_frame(
    api_key: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build the ``authenticate`` frame.

    This is the first application frame sent after the socket opens; no other
    command may be sent until the server confirms with ``auth.ok``. See
    ``contracts/protocol/sdk-ws.v1.md`` §2.
    """
    data: dict[str, Any] = {"apiKey": api_key}
    if request_id is not None:
        data["requestId"] = request_id
    return {"event": "authenticate", "data": data}


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
    return {"event": "createCall", "data": data}


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


def send_dtmf_frame(
    digits: str,
    message_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"digits": digits}
    if message_id is not None:
        data["messageId"] = message_id
    if request_id is not None:
        data["requestId"] = request_id
    return {"event": "sendDtmf", "data": data}


def cancel_frame() -> dict[str, Any]:
    return {"event": "cancel", "data": {}}


def list_agents_frame(request_id: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if request_id is not None:
        data["requestId"] = request_id
    return {"event": "listAgents", "data": data}


def get_summary_frame(call_id: str, request_id: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"callId": call_id}
    if request_id is not None:
        data["requestId"] = request_id
    return {"event": "getSummary", "data": data}


def send_sms_frame(
    to: str,
    message: str,
    call_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"to": to, "message": message}
    if call_id is not None:
        data["callId"] = call_id
    if request_id is not None:
        data["requestId"] = request_id
    return {"event": "sendSms", "data": data}


def encode(frame: dict[str, Any]) -> str:
    return json.dumps(frame)
