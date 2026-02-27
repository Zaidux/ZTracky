package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"sync"

	"github.com/golang-jwt/jwt/v5"
	"github.com/gorilla/websocket"
)

var jwtSecret = []byte(getenv("JWT_SECRET", "ztracky-secret-key-change-in-production"))

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// clientSendBuffer is the number of outbound messages buffered per client.
const clientSendBuffer = 64

var upgrader = websocket.Upgrader{
	// CheckOrigin allows all origins for self-hosted / local deployments.
	// In production, replace with a domain allowlist:
	//   return r.Header.Get("Origin") == "https://yourdomain.com"
	CheckOrigin: func(r *http.Request) bool { return true },
}

// LocationMessage is sent by clients to broadcast their location.
type LocationMessage struct {
	Type      string  `json:"type"`
	Latitude  float64 `json:"latitude"`
	Longitude float64 `json:"longitude"`
	Accuracy  float64 `json:"accuracy,omitempty"`
}

// BroadcastMessage is sent to friends with the sender's identity.
type BroadcastMessage struct {
	Type      string  `json:"type"`
	UserID    int64   `json:"user_id"`
	Username  string  `json:"username"`
	Latitude  float64 `json:"latitude"`
	Longitude float64 `json:"longitude"`
	Accuracy  float64 `json:"accuracy,omitempty"`
}

// Client represents a connected WebSocket user.
type Client struct {
	conn     *websocket.Conn
	userID   int64
	username string
	send     chan []byte
}

// Hub manages all connected clients and broadcasts location updates.
type Hub struct {
	mu      sync.RWMutex
	clients map[int64]*Client
}

func newHub() *Hub {
	return &Hub{clients: make(map[int64]*Client)}
}

func (h *Hub) register(c *Client) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.clients[c.userID] = c
	log.Printf("Client connected: user_id=%d username=%s", c.userID, c.username)
}

func (h *Hub) unregister(c *Client) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if existing, ok := h.clients[c.userID]; ok && existing == c {
		delete(h.clients, c.userID)
		close(c.send)
		log.Printf("Client disconnected: user_id=%d", c.userID)
	}
}

// broadcast sends a location update to the specified friend user IDs.
// The Python API returns the list of friend IDs that have accepted the request;
// we receive them in the "friends" field of the location message.
func (h *Hub) broadcast(senderID int64, friendIDs []int64, msg []byte) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	for _, fid := range friendIDs {
		if client, ok := h.clients[fid]; ok {
			select {
			case client.send <- msg:
			default:
				log.Printf("Send buffer full for user_id=%d, dropping message", fid)
			}
		}
	}
}

// relay forwards a directed message to a single target user.
func (h *Hub) relay(targetID, senderID int64, senderName string, incoming IncomingMessage) {
	h.mu.RLock()
	target, ok := h.clients[targetID]
	h.mu.RUnlock()
	if !ok {
		return
	}
	out := RelayMessage{
		Type:         incoming.Type,
		SenderUserID: senderID,
		SenderName:   senderName,
		Command:      incoming.Command,
		Payload:      incoming.Payload,
	}
	data, err := json.Marshal(out)
	if err != nil {
		log.Printf("relay marshal error: %v", err)
		return
	}
	select {
	case target.send <- data:
	default:
		log.Printf("Send buffer full for relay target user_id=%d, dropping", targetID)
	}
}

// onlineStatus returns which of the provided user IDs are currently connected.
func (h *Hub) onlineStatus(ids []int64) []int64 {
	h.mu.RLock()
	defer h.mu.RUnlock()
	online := make([]int64, 0, len(ids))
	for _, id := range ids {
		if _, ok := h.clients[id]; ok {
			online = append(online, id)
		}
	}
	return online
}

// IncomingMessage is the full message received from a client.
type IncomingMessage struct {
	Type      string  `json:"type"`
	Latitude  float64 `json:"latitude"`
	Longitude float64 `json:"longitude"`
	Accuracy  float64 `json:"accuracy,omitempty"`
	// Friends is the list of accepted friend user IDs for location broadcasts.
	Friends []int64 `json:"friends"`
	// TargetUserID, Command, and Payload are used for directed remote-control messages.
	TargetUserID int64  `json:"target_user_id,omitempty"`
	Command      string `json:"command,omitempty"`
	Payload      string `json:"payload,omitempty"`
}

// RelayMessage is forwarded to a specific target user for remote-control and WebRTC signalling.
type RelayMessage struct {
	Type         string `json:"type"`
	SenderUserID int64  `json:"sender_user_id"`
	SenderName   string `json:"sender_name"`
	Command      string `json:"command,omitempty"`
	Payload      string `json:"payload,omitempty"`
}

// PresenceResponse is returned by check_presence requests.
type PresenceResponse struct {
	Type      string  `json:"type"`
	OnlineIDs []int64 `json:"online_ids"`
}

var hub = newHub()

func serveWS(w http.ResponseWriter, r *http.Request) {
	// Validate JWT from query param or Authorization header.
	tokenStr := r.URL.Query().Get("token")
	if tokenStr == "" {
		http.Error(w, "missing token", http.StatusUnauthorized)
		return
	}

	claims := jwt.MapClaims{}
	tok, err := jwt.ParseWithClaims(tokenStr, claims, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, jwt.ErrSignatureInvalid
		}
		return jwtSecret, nil
	})
	if err != nil || !tok.Valid {
		http.Error(w, "invalid token", http.StatusUnauthorized)
		return
	}

	sub, ok := claims["sub"].(string)
	if !ok || sub == "" {
		http.Error(w, "invalid token claims", http.StatusUnauthorized)
		return
	}

	var userID int64
	if _, err := parseIntFromString(sub, &userID); err != nil {
		http.Error(w, "invalid user id in token", http.StatusUnauthorized)
		return
	}

	username := r.URL.Query().Get("username")

	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket upgrade error: %v", err)
		return
	}

	client := &Client{
		conn:     conn,
		userID:   userID,
		username: username,
		send:     make(chan []byte, clientSendBuffer),
	}
	hub.register(client)

	// Writer goroutine
	go func() {
		defer conn.Close()
		for msg := range client.send {
			if err := conn.WriteMessage(websocket.TextMessage, msg); err != nil {
				log.Printf("Write error for user %d: %v", client.userID, err)
				return
			}
		}
	}()

	// Reader loop (current goroutine)
	defer hub.unregister(client)
	for {
		_, data, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
				log.Printf("Read error for user %d: %v", client.userID, err)
			}
			break
		}

		var incoming IncomingMessage
		if err := json.Unmarshal(data, &incoming); err != nil {
			log.Printf("JSON parse error from user %d: %v", client.userID, err)
			continue
		}

		switch incoming.Type {
		case "location":
			out := BroadcastMessage{
				Type:      "location",
				UserID:    client.userID,
				Username:  client.username,
				Latitude:  incoming.Latitude,
				Longitude: incoming.Longitude,
				Accuracy:  incoming.Accuracy,
			}
			outData, err := json.Marshal(out)
			if err != nil {
				log.Printf("JSON marshal error: %v", err)
				continue
			}
			hub.broadcast(client.userID, incoming.Friends, outData)

		case "remote_command", "peer_offer", "peer_answer", "peer_ice":
			// Directed messages: relay to the specified target user.
			if incoming.TargetUserID > 0 {
				hub.relay(incoming.TargetUserID, client.userID, client.username, incoming)
			}

		case "check_presence":
			// Respond with which of the listed friend IDs are currently online.
			onlineIDs := hub.onlineStatus(incoming.Friends)
			resp := PresenceResponse{Type: "presence_status", OnlineIDs: onlineIDs}
			respData, err := json.Marshal(resp)
			if err != nil {
				log.Printf("presence marshal error: %v", err)
				continue
			}
			select {
			case client.send <- respData:
			default:
			}
		}
	}
}

func parseIntFromString(s string, out *int64) (int, error) {
	n, err := fmt.Sscanf(s, "%d", out)
	return n, err
}

func statsHandler(w http.ResponseWriter, r *http.Request) {
	hub.mu.RLock()
	count := len(hub.clients)
	hub.mu.RUnlock()
	w.Header().Set("Content-Type", "application/json")
	fmt.Fprintf(w, `{"online_count":%d}`, count)
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"status":"ok","service":"ztracky-location-service"}`))
}

func main() {
	port := getenv("PORT", "8001")

	http.HandleFunc("/ws", serveWS)
	http.HandleFunc("/health", healthHandler)
	http.HandleFunc("/stats", statsHandler)

	log.Printf("ZTracky location service listening on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server error: %v", err)
	}
}
