package tello

import (
	"context"
	"sync"
)

type Handler func(context.Context, Event) error

type EventEmitter struct {
	mu       sync.RWMutex
	handlers map[string][]Handler
}

func NewEventEmitter() *EventEmitter {
	return &EventEmitter{handlers: make(map[string][]Handler)}
}

func (e *EventEmitter) On(eventType string, handler Handler) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.handlers[eventType] = append(e.handlers[eventType], handler)
}

func (e *EventEmitter) Emit(ctx context.Context, eventType string, event Event) error {
	e.mu.RLock()
	handlers := append([]Handler(nil), e.handlers[eventType]...)
	e.mu.RUnlock()

	for _, handler := range handlers {
		if err := handler(ctx, event); err != nil {
			return err
		}
	}
	return nil
}
