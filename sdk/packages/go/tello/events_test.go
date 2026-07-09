package tello

import "testing"

func TestParseUserTurn(t *testing.T) {
	event := ParseEvent(map[string]any{
		"type":      "user.turn",
		"version":   "1.0",
		"sessionId": "s1",
		"callId":    "c1",
		"turnIndex": float64(2),
		"text":      "hey",
		"timestamp": "t",
	})

	if event.Type != EventTypeUserTurn || event.TurnIndex != 2 || event.Text != "hey" || event.CallID != "c1" || event.SessionID != "s1" {
		t.Fatalf("unexpected event: %+v", event)
	}
}

func TestParseErrorFrame(t *testing.T) {
	event := ParseEvent(map[string]any{
		"type":      "error",
		"version":   "1.0",
		"code":      "callRejected",
		"message":   "Call rejected",
		"requestId": "r1",
		"question":  "why?",
	})

	if event.Code != "callRejected" || event.RequestID != "r1" || event.Question != "why?" {
		t.Fatalf("unexpected error event: %+v", event)
	}
}

func TestTerminalDetection(t *testing.T) {
	if !IsTerminal(ParseEvent(map[string]any{
		"type":      "call.completed",
		"version":   "1.0",
		"callId":    "c1",
		"status":    "completed",
		"timestamp": "t",
	})) {
		t.Fatal("completed should be terminal")
	}
	if !IsTerminal(ParseEvent(map[string]any{
		"type":           "call.statusChanged",
		"version":        "1.0",
		"callId":         "c1",
		"status":         "cancelled",
		"previousStatus": "inProgress",
		"timestamp":      "t",
	})) {
		t.Fatal("cancelled should be terminal")
	}
}
