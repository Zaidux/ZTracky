package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/gorilla/websocket"
)

func makeToken(userID string) string {
	claims := jwt.MapClaims{
		"sub": userID,
		"exp": time.Now().Add(time.Hour).Unix(),
	}
	tok, _ := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString(jwtSecret)
	return tok
}

func TestHealthEndpoint(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()
	healthHandler(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	body := w.Body.String()
	if !strings.Contains(body, "ok") {
		t.Fatalf("unexpected body: %s", body)
	}
}

func TestWSRejectsNoToken(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(serveWS))
	defer srv.Close()

	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws"
	_, resp, err := websocket.DefaultDialer.Dial(url, nil)
	if err == nil {
		t.Fatal("expected connection to be rejected without token")
	}
	if resp != nil && resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", resp.StatusCode)
	}
}

func TestWSRejectsBadToken(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(serveWS))
	defer srv.Close()

	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws?token=INVALID&username=alice"
	_, resp, err := websocket.DefaultDialer.Dial(url, nil)
	if err == nil {
		t.Fatal("expected connection to be rejected with bad token")
	}
	if resp != nil && resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", resp.StatusCode)
	}
}

func TestWSAcceptsValidToken(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(serveWS))
	defer srv.Close()

	tok := makeToken("42")
	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws?token=" + tok + "&username=testuser"
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		t.Fatalf("expected connection to succeed with valid token: %v", err)
	}
	conn.Close()
}

func TestHubRegisterUnregister(t *testing.T) {
	h := newHub()
	c := &Client{userID: 1, username: "alice", send: make(chan []byte, 1)}
	h.register(c)

	h.mu.RLock()
	_, ok := h.clients[1]
	h.mu.RUnlock()
	if !ok {
		t.Fatal("client not registered")
	}

	h.unregister(c)
	h.mu.RLock()
	_, ok = h.clients[1]
	h.mu.RUnlock()
	if ok {
		t.Fatal("client should have been unregistered")
	}
}

func TestHubBroadcast(t *testing.T) {
	h := newHub()
	ch := make(chan []byte, 2)
	c := &Client{userID: 2, username: "bob", send: ch}
	h.register(c)
	defer h.unregister(c)

	msg := []byte(`{"type":"location"}`)
	h.broadcast(1, []int64{2}, msg)

	select {
	case got := <-ch:
		if string(got) != string(msg) {
			t.Fatalf("unexpected message: %s", got)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for broadcast message")
	}
}

func TestHubBroadcastNotToSelf(t *testing.T) {
	h := newHub()
	ch := make(chan []byte, 2)
	c := &Client{userID: 1, username: "alice", send: ch}
	h.register(c)
	defer h.unregister(c)

	// Sender is 1, friends list is empty → no message to anyone
	h.broadcast(1, []int64{}, []byte(`{}`))
	select {
	case <-ch:
		t.Fatal("should not receive message when not in friends list")
	case <-time.After(100 * time.Millisecond):
		// expected
	}
}
