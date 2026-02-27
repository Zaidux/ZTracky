# ZTracky 📍

**Precise, consent-based location sharing with trusted contacts.**

ZTracky lets you send a tracking request to a friend or family member. Once they accept, both of you can see each other's real-time location on a live map — useful for locating a stolen phone, keeping tabs on family, or just knowing where your friends are.

---

## Architecture

ZTracky is a **multi-language** application where each component is written in the most appropriate language:

| Service | Language | Role |
|---|---|---|
| **REST API** | Python (FastAPI) | Auth, friend requests, location persistence |
| **Real-time hub** | Go | WebSocket server for live location broadcasting |
| **Frontend** | HTML + JavaScript | Map UI, geolocation, request management |
| **Orchestration** | Docker Compose | Ties all services together |

```
┌─────────────────────────────────────────────────────┐
│                   Browser (JS)                      │
│  ┌─────────────────┐   ┌──────────────────────────┐ │
│  │  REST API calls  │   │  WebSocket (live location)│ │
│  └────────┬────────┘   └────────────┬─────────────┘ │
└───────────┼──────────────────────────┼───────────────┘
            │                          │
   ┌─────────▼──────────┐   ┌──────────▼──────────────┐
   │  Python FastAPI     │   │  Go WebSocket Service   │
   │  (port 8000)        │   │  (port 8001)            │
   │                     │   │                         │
   │  • Register/login   │   │  • JWT auth             │
   │  • Tracking requests│   │  • Hub (user → conn)    │
   │  • Location REST    │   │  • Broadcast to friends │
   │  • SQLite DB        │   │                         │
   └─────────────────────┘   └─────────────────────────┘
```

---

## Features

- 🔐 **User registration & JWT login**
- 📨 **Tracking requests** — send, accept, or reject
- 🗺 **Live map** (OpenStreetMap + Leaflet.js) with friend markers
- 📡 **Real-time updates** via Go WebSocket service
- 💾 **Persistent last-known location** via Python REST API
- 🔒 **Authorization** — you can only view locations of accepted friends
- 📱 **Mobile-friendly** responsive UI

---

## Screenshots

| Sign In | Register |
|---|---|
| ![Sign In](https://github.com/user-attachments/assets/dca4aa88-1214-43cd-9438-f3563ca7cc47) | ![Register](https://github.com/user-attachments/assets/3f8412ab-9c11-4c22-b464-26e074ced97d) |

---

## Getting Started

### Option 1 – Docker Compose (recommended)

```bash
# Clone the repo
git clone https://github.com/Zaidux/ZTracky.git
cd ZTracky

# (Optional) Set a secure secret
export JWT_SECRET=your-very-secret-key

# Build and start all services
docker compose up --build
```

Then open **http://localhost** in your browser.

### Option 2 – Run services manually

#### 1. Python REST API (port 8000)

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

API docs available at http://localhost:8000/docs

#### 2. Go WebSocket service (port 8001)

```bash
cd location-service
go run main.go
```

#### 3. Frontend

Serve the `frontend/` directory with any static file server:

```bash
cd frontend
python3 -m http.server 80
# or: npx serve .
```

> **Important:** Both services must share the same `JWT_SECRET` environment variable (defaults to `ztracky-secret-key-change-in-production`).

---

## How It Works

1. **Register** an account on either device.
2. **Send a tracking request** to a friend by username (Requests tab).
3. The friend opens the app, sees the **incoming request**, and **accepts** it.
4. Both devices now appear on each other's **live map**.
5. Location updates are sent:
   - Over **WebSocket** (Go service) for real-time updates while both are online.
   - Over **REST** (Python API) so the last-known location persists even when offline.

---

## REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/register` | Create account |
| `POST` | `/api/login` | Login (returns JWT) |
| `GET` | `/api/me` | Get current user |
| `POST` | `/api/requests/send?username=X` | Send tracking request |
| `GET` | `/api/requests` | List all requests |
| `POST` | `/api/requests/{id}/accept` | Accept a request |
| `POST` | `/api/requests/{id}/reject` | Reject a request |
| `GET` | `/api/friends` | List accepted friends |
| `POST` | `/api/location` | Update my location |
| `GET` | `/api/location/{user_id}` | Get a friend's location |
| `GET` | `/api/friends/locations` | Get all friends' locations |

---

## WebSocket Protocol (Go service)

Connect to `ws://localhost:8001/ws?token=<JWT>&username=<name>`

**Send** (client → server):
```json
{
  "type": "location",
  "latitude": 40.7128,
  "longitude": -74.0060,
  "accuracy": 15.0,
  "friends": [2, 5, 8]
}
```
The `friends` array contains the user IDs of accepted friends (obtained from `GET /api/friends`). The Go hub forwards the message only to those users if they are currently connected.

**Receive** (server → client):
```json
{
  "type": "location",
  "user_id": 3,
  "username": "alice",
  "latitude": 40.7128,
  "longitude": -74.0060,
  "accuracy": 15.0
}
```

---

## Running Tests

### Python (26 tests)

```bash
cd backend
pip install -r requirements.txt pytest httpx
pytest test_api.py -v
```

### Go (7 tests)

```bash
cd location-service
go test ./... -v
```

---

## Project Structure

```
ZTracky/
├── backend/                  # Python FastAPI REST API
│   ├── main.py               # Routes & schemas
│   ├── database.py           # SQLAlchemy models (User, TrackingRequest, Location)
│   ├── auth.py               # JWT & password helpers
│   ├── test_api.py           # 26 pytest integration tests
│   ├── requirements.txt
│   └── Dockerfile
├── location-service/         # Go real-time WebSocket hub
│   ├── main.go               # Hub + WebSocket handler + JWT validation
│   ├── main_test.go          # 7 Go unit/integration tests
│   ├── go.mod
│   └── Dockerfile
├── frontend/                 # HTML/CSS/JavaScript SPA
│   ├── index.html            # App shell
│   ├── app.js                # All client logic (auth, map, WS, requests)
│   ├── style.css             # Dark-mode responsive styles
│   └── Dockerfile            # Served by nginx
└── docker-compose.yml        # Orchestrates all three services
```
