package tello

type TelloError struct {
	Code     string
	Message  string
	Question string
}

func (e *TelloError) Error() string {
	return e.Message
}

type ConnectionClosedError struct{ TelloError }
type SessionReplacedError struct{ TelloError }
type AuthenticationError struct{ TelloError }
type ValidationError struct{ TelloError }
type CallAlreadyActiveError struct{ TelloError }
type NoActiveCallError struct{ TelloError }
type CallRejectedError struct{ TelloError }
type TelloServerError struct{ TelloError }

func ErrorFor(code, message, question string) error {
	base := TelloError{Code: code, Message: message, Question: question}
	switch code {
	case "unauthenticated":
		return &AuthenticationError{base}
	case "to_required":
		return &ValidationError{base}
	case "agent_id_required":
		return &ValidationError{base}
	case "call_already_active":
		return &CallAlreadyActiveError{base}
	case "no_active_call":
		return &NoActiveCallError{base}
	case "call_rejected":
		return &CallRejectedError{base}
	case "internal_error":
		fallthrough
	default:
		return &TelloServerError{base}
	}
}
