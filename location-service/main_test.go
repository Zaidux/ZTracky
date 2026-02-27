package main

import (
	"encoding/json"
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

func TestHubRelay(t *testing.T) {
	h := newHub()

	// Sender
	sender := &Client{userID: 1, username: "alice", send: make(chan []byte, 2)}
	// Target
	target := &Client{userID: 2, username: "bob", send: make(chan []byte, 2)}
	h.register(sender)
	h.register(target)
	defer h.unregister(sender)
	defer h.unregister(target)

	inc := IncomingMessage{Type: "remote_command", Command: "lock", TargetUserID: 2}
	h.relay(2, 1, "alice", inc)

	select {
	case msg := <-target.send:
		var rm RelayMessage
		if err := json.Unmarshal(msg, &rm); err != nil {
			t.Fatalf("unmarshal error: %v", err)
		}
		if rm.SenderUserID != 1 || rm.Command != "lock" || rm.Type != "remote_command" {
			t.Fatalf("unexpected relay message: %+v", rm)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for relayed message")
	}
}

func TestHubRelayUnknownTarget(t *testing.T) {
	h := newHub()
	// Relay to a non-existent user should not panic
	inc := IncomingMessage{Type: "remote_command", Command: "lock", TargetUserID: 999}
	h.relay(999, 1, "alice", inc) // should silently no-op
}

func TestHubOnlineStatus(t *testing.T) {
	h := newHub()
	c1 := &Client{userID: 10, username: "u10", send: make(chan []byte, 1)}
	c2 := &Client{userID: 20, username: "u20", send: make(chan []byte, 1)}
	h.register(c1)
	h.register(c2)
	defer h.unregister(c1)
	defer h.unregister(c2)

	online := h.onlineStatus([]int64{10, 20, 30})
	if len(online) != 2 {
		t.Fatalf("expected 2 online, got %d: %v", len(online), online)
	}
	for _, id := range online {
		if id != 10 && id != 20 {
			t.Fatalf("unexpected online id: %d", id)
		}
	}
}

func TestWSCheckPresence(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(serveWS))
	defer srv.Close()

	tok := makeToken("1")
	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws?token=" + tok + "&username=alice"

	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		t.Fatalf("dial failed: %v", err)
	}
	defer conn.Close()

	// Send check_presence with no friends → should get back empty online_ids
	msg := `{"type":"check_presence","friends":[]}`
	if err := conn.WriteMessage(websocket.TextMessage, []byte(msg)); err != nil {
		t.Fatalf("write error: %v", err)
	}

	conn.SetReadDeadline(time.Now().Add(2 * time.Second))
	_, data, err := conn.ReadMessage()
	if err != nil {
		t.Fatalf("read error: %v", err)
	}
	var resp PresenceResponse
	if err := json.Unmarshal(data, &resp); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}
	if resp.Type != "presence_status" {
		t.Fatalf("unexpected type: %s", resp.Type)
	}
}

func TestWSRelayRemoteCommand(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(serveWS))
	defer srv.Close()

	// Alice (user 1) will send a command, Bob (user 2) will receive it
	tokAlice := makeToken("1")
	tokBob := makeToken("2")

	urlAlice := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws?token=" + tokAlice + "&username=alice"
	urlBob := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws?token=" + tokBob + "&username=bob"

	connAlice, _, err := websocket.DefaultDialer.Dial(urlAlice, nil)
	if err != nil {
		t.Fatalf("alice dial failed: %v", err)
	}
	defer connAlice.Close()

	connBob, _, err := websocket.DefaultDialer.Dial(urlBob, nil)
	if err != nil {
		t.Fatalf("bob dial failed: %v", err)
	}
	defer connBob.Close()

	// Alice sends lock command to Bob (user_id=2)
	cmd := `{"type":"remote_command","target_user_id":2,"command":"lock"}`
	if err := connAlice.WriteMessage(websocket.TextMessage, []byte(cmd)); err != nil {
		t.Fatalf("alice write error: %v", err)
	}

	// Bob should receive it
	connBob.SetReadDeadline(time.Now().Add(2 * time.Second))
	_, data, err := connBob.ReadMessage()
	if err != nil {
		t.Fatalf("bob read error: %v", err)
	}
	var rm RelayMessage
	if err := json.Unmarshal(data, &rm); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}
	if rm.Command != "lock" || rm.SenderUserID != 1 || rm.SenderName != "alice" {
		t.Fatalf("unexpected relay message: %+v", rm)
	}
}

func TestStatsEndpoint(t *testing.T) {
	// The stats endpoint should return online_count reflecting current hub state
	srv := httptest.NewServer(http.HandlerFunc(statsHandler))
	defer srv.Close()

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/stats", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("request failed: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	var body map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode error: %v", err)
	}
	if _, ok := body["online_count"]; !ok {
		t.Fatal("response missing online_count field")
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
