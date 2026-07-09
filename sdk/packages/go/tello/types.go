package tello

const ProtocolVersion = "1.0"

const (
	EventTypeUserTurn          = "user.turn"
	EventTypeAgentTurn         = "agent.turn"
	EventTypeCallStatusChanged = "call.statusChanged"
	EventTypeCallCompleted     = "call.completed"
	EventTypeCallNoAnswer      = "call.noAnswer"
	EventTypeCallFailed        = "call.failed"
	EventTypeError             = "error"
	EventTypeDisconnected      = "disconnected"
)

const (
	StatusQueued       = "queued"
	StatusDialing      = "dialing"
	StatusRinging      = "ringing"
	StatusInProgress   = "inProgress"
	StatusTransferring = "transferring"
	StatusCompleted    = "completed"
	StatusNoAnswer     = "noAnswer"
	StatusFailed       = "failed"
	StatusCancelled    = "cancelled"
)

type Event struct {
	Type           string         `json:"type"`
	Version        string         `json:"version"`
	SessionID      string         `json:"sessionId"`
	CallID         string         `json:"callId"`
	Timestamp      string         `json:"timestamp"`
	Raw            map[string]any `json:"-"`
	TurnIndex      int            `json:"turnIndex"`
	Text           string         `json:"text"`
	Status         string         `json:"status"`
	PreviousStatus string         `json:"previousStatus"`
	FailureReason  string         `json:"failureReason"`
	Code           string         `json:"code"`
	Message        string         `json:"message"`
	RequestID      string         `json:"requestId"`
	Question       string         `json:"question"`
}
