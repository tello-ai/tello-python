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
	case "toRequired":
		return &ValidationError{base}
	case "agentIdRequired":
		return &ValidationError{base}
	case "callAlreadyActive":
		return &CallAlreadyActiveError{base}
	case "noActiveCall":
		return &NoActiveCallError{base}
	case "callRejected":
		return &CallRejectedError{base}
	case "internalError":
		fallthrough
	default:
		return &TelloServerError{base}
	}
}
