from tello.commands import answer_frame, cancel_frame, create_call_frame
from tello.events import (
    ErrorEvent,
    EventType,
    StatusChangedEvent,
    TerminalEvent,
    TurnEvent,
    is_terminal,
    parse_event,
)


def test_create_call_frame_uses_envelope_and_camelcase():
    frame = create_call_frame("+821012345678", "agent-1", "hi", {"src": "test"}, "r1")
    assert frame == {
        "event": "create_call",
        "data": {
            "to": "+821012345678",
            "agentId": "agent-1",
            "prompt": "hi",
            "metadata": {"src": "test"},
            "requestId": "r1",
        },
    }


def test_create_call_frame_omits_optional_fields():
    assert create_call_frame("+821012345678", "agent-1") == {
        "event": "create_call",
        "data": {"to": "+821012345678", "agentId": "agent-1", "prompt": ""},
    }


def test_answer_and_cancel_frames():
    assert answer_frame("yo", "m1") == {"event": "answer", "data": {"text": "yo", "messageId": "m1"}}
    assert cancel_frame() == {"event": "cancel", "data": {}}


def test_parse_user_turn():
    event = parse_event(
        {
            "type": "user.turn",
            "version": "1.0",
            "sessionId": "s1",
            "callId": "c1",
            "turnIndex": 2,
            "text": "hey",
            "timestamp": "t",
        }
    )
    assert isinstance(event, TurnEvent)
    assert (event.turn_index, event.text, event.call_id, event.session_id) == (2, "hey", "c1", "s1")


def test_parse_status_changed():
    event = parse_event(
        {
            "type": "call.statusChanged",
            "version": "1.0",
            "sessionId": "s1",
            "callId": "c1",
            "status": "inProgress",
            "previousStatus": "queued",
            "timestamp": "t",
        }
    )
    assert isinstance(event, StatusChangedEvent)
    assert (event.status, event.previous_status) == ("inProgress", "queued")


def test_parse_error_frame_flat_with_request_id():
    event = parse_event(
        {"type": "error", "version": "1.0", "code": "noActiveCall", "message": "No active call", "requestId": "r1"}
    )
    assert isinstance(event, ErrorEvent)
    assert (event.code, event.request_id) == ("noActiveCall", "r1")


def test_parse_call_rejected_carries_question():
    event = parse_event(
        {"type": "error", "version": "1.0", "code": "callRejected", "message": "Call rejected", "question": "why?"}
    )
    assert isinstance(event, ErrorEvent)
    assert event.question == "why?"


def test_terminal_detection():
    completed = parse_event(
        {
            "type": "call.completed",
            "version": "1.0",
            "sessionId": "s1",
            "callId": "c1",
            "status": "completed",
            "timestamp": "t",
        }
    )
    assert isinstance(completed, TerminalEvent)
    assert is_terminal(completed)

    cancelled = parse_event(
        {
            "type": "call.statusChanged",
            "version": "1.0",
            "sessionId": "s1",
            "callId": "c1",
            "status": "cancelled",
            "previousStatus": "inProgress",
            "timestamp": "t",
        }
    )
    assert is_terminal(cancelled)

    non_terminal = parse_event(
        {
            "type": "call.statusChanged",
            "version": "1.0",
            "sessionId": "s1",
            "callId": "c1",
            "status": "inProgress",
            "previousStatus": "queued",
            "timestamp": "t",
        }
    )
    assert not is_terminal(non_terminal)


def test_parse_no_answer_terminal_fields():
    event = parse_event(
        {
            "type": "call.noAnswer",
            "version": "1.0",
            "sessionId": "s1",
            "callId": "c1",
            "status": "noAnswer",
            "failureReason": "ring timeout",
            "timestamp": "t",
        }
    )
    assert isinstance(event, TerminalEvent)
    assert (event.status, event.failure_reason) == ("noAnswer", "ring timeout")
    assert is_terminal(event)


def test_unknown_event_type_falls_back_to_base_event():
    event = parse_event(
        {"type": "future.thing", "version": "1.0", "sessionId": "s1", "callId": "c1", "timestamp": "t"}
    )
    assert event.type == "future.thing"
    assert event.raw["type"] == "future.thing"


def test_event_type_constants():
    assert EventType.USER_TURN == "user.turn"
    assert EventType.CALL_STATUS_CHANGED == "call.statusChanged"
    assert EventType.CALL_NO_ANSWER == "call.noAnswer"
