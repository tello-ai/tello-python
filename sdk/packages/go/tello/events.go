package tello

func ParseEvent(frame map[string]any) Event {
	eventType := stringValue(frame["type"])
	event := Event{
		Type:      eventType,
		Version:   stringValue(frame["version"]),
		CallID:    stringValue(frame["call_id"]),
		Timestamp: stringValue(frame["timestamp"]),
		Raw:       frame,
	}

	switch eventType {
	case EventTypeUserTurn, EventTypeAgentTurn:
		event.TurnIndex = intValue(frame["turn_index"])
		event.Text = stringValue(frame["text"])
	case EventTypeCallStatusChanged:
		event.Status = stringValue(frame["status"])
		event.PreviousStatus = stringValue(frame["previous_status"])
	case EventTypeCallCompleted, EventTypeCallNoAnswer, EventTypeCallFailed:
		event.Status = stringValue(frame["status"])
		event.FailureReason = stringValue(frame["failure_reason"])
	case EventTypeError:
		event.Code = stringValue(frame["code"])
		event.Message = stringValue(frame["message"])
		event.RequestID = stringValue(frame["request_id"])
		event.Question = stringValue(frame["question"])
	}

	return event
}

func IsTerminal(event Event) bool {
	switch event.Type {
	case EventTypeCallCompleted, EventTypeCallNoAnswer, EventTypeCallFailed:
		return true
	case EventTypeCallStatusChanged:
		return event.Status == "cancelled"
	default:
		return false
	}
}

func stringValue(value any) string {
	if text, ok := value.(string); ok {
		return text
	}
	return ""
}

func intValue(value any) int {
	switch number := value.(type) {
	case int:
		return number
	case int64:
		return int(number)
	case float64:
		return int(number)
	default:
		return 0
	}
}
