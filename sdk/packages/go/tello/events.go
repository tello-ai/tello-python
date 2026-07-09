package tello

func ParseEvent(frame map[string]any) Event {
	eventType := stringValue(frame["type"])
	event := Event{
		Type:      eventType,
		Version:   stringValue(frame["version"]),
		SessionID: stringValue(frame["sessionId"]),
		CallID:    stringValue(frame["callId"]),
		Timestamp: stringValue(frame["timestamp"]),
		Raw:       frame,
	}

	switch eventType {
	case EventTypeUserTurn, EventTypeAgentTurn:
		event.TurnIndex = intValue(frame["turnIndex"])
		event.Text = stringValue(frame["text"])
	case EventTypeCallStatusChanged:
		event.Status = stringValue(frame["status"])
		event.PreviousStatus = stringValue(frame["previousStatus"])
	case EventTypeCallCompleted, EventTypeCallNoAnswer, EventTypeCallFailed:
		event.Status = stringValue(frame["status"])
		event.FailureReason = stringValue(frame["failureReason"])
	case EventTypeError:
		event.Code = stringValue(frame["code"])
		event.Message = stringValue(frame["message"])
		event.RequestID = stringValue(frame["requestId"])
		event.Question = stringValue(frame["question"])
	}

	return event
}

func IsTerminal(event Event) bool {
	switch event.Type {
	case EventTypeCallCompleted, EventTypeCallNoAnswer, EventTypeCallFailed:
		return true
	case EventTypeCallStatusChanged:
		return event.Status == StatusCancelled
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
