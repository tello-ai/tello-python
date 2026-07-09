package tello

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func TestClientSendsAuthorizationHeaderAndCreateCallFrame(t *testing.T) {
	var gotAuth string
	var gotFrame map[string]any
	done := make(chan struct{})
	upgrader := websocket.Upgrader{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer close(done)
		gotAuth = r.Header.Get("Authorization")
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Error(err)
			return
		}
		defer conn.Close()
		if err := conn.ReadJSON(&gotFrame); err != nil {
			t.Error(err)
		}
	}))
	defer server.Close()

	client, err := NewClient("key-1", WithURL("ws"+server.URL[len("http"):]+"/sdk"))
	if err != nil {
		t.Fatal(err)
	}
	if err := client.Connect(context.Background()); err != nil {
		t.Fatal(err)
	}
	defer client.Close()

	if err := client.CreateCall(context.Background(), "+821012345678", "agent-1", "prompt", map[string]any{"src": "test"}, "r1"); err != nil {
		t.Fatal(err)
	}
	<-done

	if gotAuth != "Bearer key-1" {
		t.Fatalf("expected auth header, got %q", gotAuth)
	}
	assertJSONEqual(t, map[string]any{
		"event": "create_call",
		"data": map[string]any{
			"to":        "+821012345678",
			"agentId":   "agent-1",
			"prompt":    "prompt",
			"metadata":  map[string]any{"src": "test"},
			"requestId": "r1",
		},
	}, gotFrame)
}

func TestClientEmitsUserTurnsAndSurfacesCallRejection(t *testing.T) {
	upgrader := websocket.Upgrader{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Error(err)
			return
		}
		defer conn.Close()
		var ignored map[string]any
		if err := conn.ReadJSON(&ignored); err != nil {
			t.Error(err)
			return
		}
		_ = conn.WriteJSON(map[string]any{
			"type":       "user.turn",
			"version":    "1.0",
			"call_id":    "c1",
			"turn_index": 1,
			"text":       "hello",
			"timestamp":  "t",
		})
		_ = conn.WriteJSON(map[string]any{
			"type":     "error",
			"version":  "1.0",
			"code":     "call_rejected",
			"message":  "Call rejected",
			"question": "why?",
		})
	}))
	defer server.Close()

	client, err := NewClient("key-1", WithURL("ws"+server.URL[len("http"):]+"/sdk"))
	if err != nil {
		t.Fatal(err)
	}
	var turns []string
	client.On(EventTypeUserTurn, func(_ context.Context, event Event) error {
		turns = append(turns, event.Text)
		return nil
	})
	if err := client.Connect(context.Background()); err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	if err := client.CreateCall(context.Background(), "+821012345678", "agent-1", "", nil, ""); err != nil {
		t.Fatal(err)
	}

	err = client.WaitClosed(context.Background())
	var rejected *CallRejectedError
	if !errors.As(err, &rejected) {
		t.Fatalf("expected CallRejectedError, got %T: %v", err, err)
	}
	if rejected.Question != "why?" {
		t.Fatalf("expected question, got %q", rejected.Question)
	}
	if len(turns) != 1 || turns[0] != "hello" {
		encoded, _ := json.Marshal(turns)
		t.Fatalf("unexpected turns: %s", encoded)
	}
}

func TestClientReconnectReportsSecondConnectionClose(t *testing.T) {
	upgrader := websocket.Upgrader{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Error(err)
			return
		}
		_ = conn.Close()
	}))
	defer server.Close()

	client, err := NewClient("key-1", WithURL("ws"+server.URL[len("http"):]+"/sdk"))
	if err != nil {
		t.Fatal(err)
	}
	if err := client.Connect(context.Background()); err != nil {
		t.Fatal(err)
	}
	_ = client.Close()

	if err := client.Connect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := client.CreateCall(context.Background(), "+821012345678", "agent-1", "", nil, ""); err != nil {
		t.Fatal(err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	err = client.WaitClosed(ctx)
	var closed *ConnectionClosedError
	if !errors.As(err, &closed) {
		t.Fatalf("expected ConnectionClosedError, got %T: %v", err, err)
	}
}

func TestClientIgnoresStaleCloseFromPreviousConnection(t *testing.T) {
	upgrader := websocket.Upgrader{}
	firstReady := make(chan *websocket.Conn, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Error(err)
			return
		}
		select {
		case firstReady <- conn:
			return
		default:
		}
		var ignored map[string]any
		if err := conn.ReadJSON(&ignored); err != nil {
			t.Error(err)
			return
		}
		first := <-firstReady
		_ = first.Close()
		time.Sleep(20 * time.Millisecond)
		_ = conn.WriteJSON(map[string]any{
			"type":      "call.completed",
			"version":   "1.0",
			"call_id":   "c1",
			"status":    "completed",
			"timestamp": "t",
		})
	}))
	defer server.Close()

	client, err := NewClient("key-1", WithURL("ws"+server.URL[len("http"):]+"/sdk"))
	if err != nil {
		t.Fatal(err)
	}
	if err := client.Connect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := client.Connect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := client.CreateCall(context.Background(), "+821012345678", "agent-1", "", nil, ""); err != nil {
		t.Fatal(err)
	}

	if err := client.WaitClosed(context.Background()); err != nil {
		t.Fatalf("expected second call completion, got %T: %v", err, err)
	}
}

func TestClientReturnsTypedErrorForCommandAfterClose(t *testing.T) {
	upgrader := websocket.Upgrader{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Error(err)
			return
		}
		_ = conn.Close()
	}))
	defer server.Close()

	client, err := NewClient("key-1", WithURL("ws"+server.URL[len("http"):]+"/sdk"))
	if err != nil {
		t.Fatal(err)
	}
	if err := client.Connect(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := client.WaitClosed(context.Background()); err != nil {
		t.Fatal(err)
	}

	err = client.Answer(context.Background(), "hello", "", "")
	var closed *ConnectionClosedError
	if !errors.As(err, &closed) {
		t.Fatalf("expected ConnectionClosedError, got %T: %v", err, err)
	}
}

func TestClientSerializesConcurrentCommandWrites(t *testing.T) {
	upgrader := websocket.Upgrader{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Error(err)
			return
		}
		defer conn.Close()
		for {
			var ignored map[string]any
			if err := conn.ReadJSON(&ignored); err != nil {
				return
			}
		}
	}))
	defer server.Close()

	client, err := NewClient("key-1", WithURL("ws"+server.URL[len("http"):]+"/sdk"))
	if err != nil {
		t.Fatal(err)
	}
	if err := client.Connect(context.Background()); err != nil {
		t.Fatal(err)
	}
	defer client.Close()

	var wg sync.WaitGroup
	errs := make(chan error, 40)
	for i := 0; i < 20; i++ {
		wg.Add(2)
		go func() {
			defer wg.Done()
			errs <- client.Answer(context.Background(), "hello", "", "")
		}()
		go func() {
			defer wg.Done()
			errs <- client.Cancel(context.Background())
		}()
	}
	wg.Wait()
	close(errs)

	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
}
