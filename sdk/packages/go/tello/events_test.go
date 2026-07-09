package tello

import "testing"

func TestParseUserTurn(t *testing.T) {
	event := ParseEvent(map[string]any{
		"type":       "user.turn",
		"version":    "1.0",
		"call_id":    "c1",
		"turn_index": float64(2),
		"text":       "hey",
		"timestamp":  "t",
	})

	if event.Type != EventTypeUserTurn || event.TurnIndex != 2 || event.Text != "hey" || event.CallID != "c1" {
		t.Fatalf("unexpected event: %+v", event)
	}
}

func TestParseErrorFrame(t *testing.T) {
	event := ParseEvent(map[string]any{
		"type":       "error",
		"version":    "1.0",
		"code":       "call_rejected",
		"message":    "Call rejected",
		"request_id": "r1",
		"question":   "why?",
	})

	if event.Code != "call_rejected" || event.RequestID != "r1" || event.Question != "why?" {
		t.Fatalf("unexpected error event: %+v", event)
	}
}

func TestTerminalDetection(t *testing.T) {
	if !IsTerminal(ParseEvent(map[string]any{
		"type":      "call.completed",
		"version":   "1.0",
		"call_id":   "c1",
		"status":    "completed",
		"timestamp": "t",
	})) {
		t.Fatal("completed should be terminal")
	}
	if !IsTerminal(ParseEvent(map[string]any{
		"type":            "call.status_changed",
		"version":         "1.0",
		"call_id":         "c1",
		"status":          "cancelled",
		"previous_status": "in_progress",
		"timestamp":       "t",
	})) {
		t.Fatal("cancelled should be terminal")
	}
}
