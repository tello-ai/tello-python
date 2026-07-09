package tello

const ProtocolVersion = "1.0"

const (
	EventTypeUserTurn          = "user.turn"
	EventTypeAgentTurn         = "agent.turn"
	EventTypeCallStatusChanged = "call.status_changed"
	EventTypeCallCompleted     = "call.completed"
	EventTypeCallNoAnswer      = "call.no_answer"
	EventTypeCallFailed        = "call.failed"
	EventTypeError             = "error"
	EventTypeDisconnected      = "disconnected"
)

type Event struct {
	Type           string
	Version        string
	CallID         string
	Timestamp      string
	Raw            map[string]any
	TurnIndex      int
	Text           string
	Status         string
	PreviousStatus string
	FailureReason  string
	Code           string
	Message        string
	RequestID      string
	Question       string
}
