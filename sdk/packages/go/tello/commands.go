package tello

import "encoding/json"

type CommandFrame map[string]any

func CreateCallFrame(agentID, prompt string, metadata map[string]any, requestID string) CommandFrame {
	data := map[string]any{
		"agentId": agentID,
		"prompt":  prompt,
	}
	if metadata != nil {
		data["metadata"] = metadata
	}
	if requestID != "" {
		data["requestId"] = requestID
	}
	return CommandFrame{"event": "create_call", "data": data}
}

func AnswerFrame(text, messageID, requestID string) CommandFrame {
	data := map[string]any{"text": text}
	if messageID != "" {
		data["messageId"] = messageID
	}
	if requestID != "" {
		data["requestId"] = requestID
	}
	return CommandFrame{"event": "answer", "data": data}
}

func CancelFrame() CommandFrame {
	return CommandFrame{"event": "cancel", "data": map[string]any{}}
}

func Encode(frame CommandFrame) ([]byte, error) {
	return json.Marshal(frame)
}
