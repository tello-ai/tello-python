package tello

import (
	"context"
	"testing"
)

func TestEmitterCallsHandlersInRegistrationOrder(t *testing.T) {
	emitter := NewEventEmitter()
	var seen []int

	emitter.On("x", func(_ context.Context, event Event) error {
		seen = append(seen, event.TurnIndex)
		return nil
	})
	emitter.On("x", func(_ context.Context, event Event) error {
		seen = append(seen, event.TurnIndex+1)
		return nil
	})

	if err := emitter.Emit(context.Background(), "x", Event{TurnIndex: 1}); err != nil {
		t.Fatal(err)
	}
	if len(seen) != 2 || seen[0] != 1 || seen[1] != 2 {
		t.Fatalf("unexpected handler order: %v", seen)
	}
}
