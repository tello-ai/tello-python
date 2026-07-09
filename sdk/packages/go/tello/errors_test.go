package tello

import (
	"errors"
	"testing"
)

func TestErrorForMapsCodes(t *testing.T) {
	err := ErrorFor("no_active_call", "No active call", "")
	var noActive *NoActiveCallError
	if !errors.As(err, &noActive) {
		t.Fatalf("expected NoActiveCallError, got %T", err)
	}

	err = ErrorFor("to_required", "to is required", "")
	var validation *ValidationError
	if !errors.As(err, &validation) {
		t.Fatalf("expected ValidationError, got %T", err)
	}
}

func TestCallRejectedPreservesQuestion(t *testing.T) {
	err := ErrorFor("call_rejected", "Call rejected", "why?")
	var rejected *CallRejectedError
	if !errors.As(err, &rejected) {
		t.Fatalf("expected CallRejectedError, got %T", err)
	}
	if rejected.Question != "why?" {
		t.Fatalf("expected question, got %q", rejected.Question)
	}
}
