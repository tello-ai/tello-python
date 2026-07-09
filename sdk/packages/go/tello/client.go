package tello

import (
	"context"
	"errors"
	"net/http"
	"sync"

	"github.com/gorilla/websocket"
)

const (
	closeUnauthenticated = 4401
	closeSessionReplaced = 4429
)

type Client struct {
	*EventEmitter
	config   Config
	conn     *websocket.Conn
	mu       sync.Mutex
	writeMu  sync.Mutex
	callDone chan struct{}
	closed   chan struct{}
	closeErr error
	callErr  error
	active   bool
	callGen  int
	connGen  int
}

func NewClient(apiKey string, options ...Option) (*Client, error) {
	config, err := resolveConfig(apiKey, options...)
	if err != nil {
		return nil, err
	}
	return &Client{
		EventEmitter: NewEventEmitter(),
		config:       config,
		callDone:     make(chan struct{}),
		closed:       make(chan struct{}),
	}, nil
}

func (c *Client) Connect(ctx context.Context) error {
	dialer := websocket.Dialer{HandshakeTimeout: c.config.OpenTimeout}
	headers := http.Header{"Authorization": []string{"Bearer " + c.config.APIKey}}
	conn, _, err := dialer.DialContext(ctx, c.config.URL, headers)
	if err != nil {
		return err
	}
	c.mu.Lock()
	c.conn = conn
	c.connGen++
	gen := c.connGen
	c.callDone = make(chan struct{})
	c.closed = make(chan struct{})
	c.closeErr = nil
	c.callErr = nil
	c.mu.Unlock()
	go c.recvLoop(gen, conn)
	return nil
}

func (c *Client) Close() error {
	c.mu.Lock()
	conn := c.conn
	c.mu.Unlock()
	if conn == nil {
		return nil
	}
	return conn.Close()
}

func (c *Client) WaitClosed(ctx context.Context) error {
	c.mu.Lock()
	callDone := c.callDone
	closed := c.closed
	c.mu.Unlock()

	select {
	case <-callDone:
	case <-closed:
	case <-ctx.Done():
		return ctx.Err()
	}

	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closeErr != nil {
		return c.closeErr
	}
	if c.callErr != nil {
		err := c.callErr
		c.callErr = nil
		return err
	}
	return nil
}

func (c *Client) CreateCall(ctx context.Context, agentID, prompt string, metadata map[string]any, requestID string) error {
	c.mu.Lock()
	c.callGen++
	c.callDone = make(chan struct{})
	c.callErr = nil
	c.active = true
	c.mu.Unlock()
	return c.send(ctx, CreateCallFrame(agentID, prompt, metadata, requestID))
}

func (c *Client) Answer(ctx context.Context, text, messageID, requestID string) error {
	return c.send(ctx, AnswerFrame(text, messageID, requestID))
}

func (c *Client) Cancel(ctx context.Context) error {
	return c.send(ctx, CancelFrame())
}

func (c *Client) send(_ context.Context, frame CommandFrame) error {
	c.mu.Lock()
	conn := c.conn
	closeErr := c.closeErr
	c.mu.Unlock()
	if closeErr != nil {
		return closeErr
	}
	if conn == nil {
		return &ConnectionClosedError{TelloError{Message: "client is not connected"}}
	}
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	if err := conn.WriteJSON(frame); err != nil {
		return &ConnectionClosedError{TelloError{Message: err.Error()}}
	}
	return nil
}

func (c *Client) recvLoop(gen int, conn *websocket.Conn) {
	for {
		var frame map[string]any
		if err := conn.ReadJSON(&frame); err != nil {
			c.noteClose(gen, err)
			c.finish(gen)
			return
		}
		c.dispatch(gen, frame)
	}
}

func (c *Client) dispatch(gen int, frame map[string]any) {
	c.mu.Lock()
	if gen != c.connGen {
		c.mu.Unlock()
		return
	}
	c.mu.Unlock()

	event := ParseEvent(frame)
	if event.Type == EventTypeError {
		err := ErrorFor(event.Code, event.Message, event.Question)
		c.mu.Lock()
		if event.Code == "unauthenticated" {
			c.closeErr = err
		} else if c.active && event.Code != "no_active_call" && event.Code != "call_already_active" {
			c.callErr = err
			c.active = false
			closeIfOpen(c.callDone)
		}
		c.mu.Unlock()
		_ = c.Emit(context.Background(), EventTypeError, event)
		return
	}

	c.mu.Lock()
	callGen := c.callGen
	c.mu.Unlock()
	_ = c.Emit(context.Background(), event.Type, event)
	c.mu.Lock()
	if IsTerminal(event) && c.callGen == callGen {
		c.active = false
		closeIfOpen(c.callDone)
	}
	c.mu.Unlock()
}

func (c *Client) noteClose(gen int, err error) {
	var closeErr *websocket.CloseError
	c.mu.Lock()
	defer c.mu.Unlock()
	if gen != c.connGen {
		return
	}
	if c.closeErr != nil {
		return
	}
	if errors.As(err, &closeErr) {
		switch closeErr.Code {
		case closeUnauthenticated:
			c.closeErr = &AuthenticationError{TelloError{Code: "unauthenticated", Message: closeErr.Text}}
		case closeSessionReplaced:
			c.closeErr = &SessionReplacedError{TelloError{Message: closeErr.Text}}
		}
	}
	if c.closeErr == nil && c.active {
		c.closeErr = &ConnectionClosedError{TelloError{Message: "connection closed before call terminated"}}
	}
}

func (c *Client) finish(gen int) {
	c.mu.Lock()
	if gen != c.connGen {
		c.mu.Unlock()
		return
	}
	c.active = false
	c.conn = nil
	closeIfOpen(c.closed)
	closeIfOpen(c.callDone)
	c.mu.Unlock()
	_ = c.Emit(context.Background(), EventTypeDisconnected, Event{Type: EventTypeDisconnected, Raw: map[string]any{}})
}

func closeIfOpen(ch chan struct{}) {
	select {
	case <-ch:
	default:
		close(ch)
	}
}
