# 📍 ZTracky — Multi-Language Location Tracking App

ZTracky is a real-time, privacy-first location-sharing and device-security platform built with **Python**, **Go**, **JavaScript/HTML/CSS**, and **Solidity**. Friends mutually opt-in before any location is shared.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Browser / PWA (JavaScript + HTML + CSS)                │
│  • Leaflet map  • WebRTC  • MetaMask  • Service Worker  │
└────────────┬────────────────────────┬───────────────────┘
             │ REST (HTTP)            │ WebSocket
             ▼                        ▼
┌────────────────────┐   ┌───────────────────────────────┐
│  Python FastAPI    │   │  Go WebSocket Hub             │
│  :8000             │   │  :8001                        │
│  • Auth (JWT)      │   │  • Real-time location relay   │
│  • Tracking reqs   │   │  • WebRTC P2P signalling      │
│  • Geofences       │   │  • Presence checks            │
│  • Chat history    │   │  • /stats  /online-users      │
│  • Payments        │   └───────────────────────────────┘
│  • Admin           │
│  • SMS (Twilio)    │   ┌───────────────────────────────┐
└────────────────────┘   │  Solidity Smart Contract      │
             │           │  ZTrackySubscription.sol      │
             ▼           │  • subscribe()  • transferETH │
      SQLite / Postgres  │  • transferERC20  • withdraw  │
                         └───────────────────────────────┘
```

---

## ✨ Features

### 🆓 Free Tier
| Feature | Details |
|---|---|
| Mutual friend tracking | Both parties must accept before location is shared |
| Real-time location | Go WebSocket hub, updates every 30 s |
| Tracking requests | Send / accept / reject via friend-request flow |
| Remote Control | Screen share (WebRTC P2P), remote lock, stealth mode |
| Battery-saver mode | Haversine movement threshold, Page Visibility API throttle |
| SMS Lost-Phone | Twilio SMS with one-time deep link — no app install needed |
| Offline queueing | Service Worker + IndexedDB + Background Sync |

### ⭐ Premium Tier — $9.99/mo
| Feature | Details |
|---|---|
| Location History | Last 100 GPS points stored; route playback animation on map |
| Route Playback | Animated polyline + dot replaying your full path |
| In-App Chat | Real-time messages with friends (also relayed via WebSocket) |
| Social Account Links | WhatsApp & Facebook deep links for quick out-of-app chat |
| Geofence Alerts | Draw radius zones; enter/exit fires browser notifications |
| Nearby Phones Detection | Count devices online within N metres (useful when friend's phone is off) |
| **Call-Based Tracking** | Enter a suspicious caller's phone number; ZTracky uses Twilio Lookup to identify carrier + country and cross-references nearby online devices to produce a confidence-radius zone on the map — valuable in kidnap/ransom scenarios |
| **Trail Navigation** | Turn-by-turn route from your location to any friend's last known position; choose driving / walking / cycling; optional avoid-highways filter; powered by OSRM with graceful straight-line fallback |
| Priority GPS Updates | 10-second minimum interval |
| Unlimited Friends | Free plan: 5 friends maximum |

### 🛡 Admin Panel (`/admin.html`)
| Feature | Details |
|---|---|
| Stats Dashboard | Total users · Live online count · Premium count · Revenue · Bug reports |
| User Management | List, upgrade, downgrade any user |
| **Free Premium Grants** | Grant free premium access to users (for beta testers, bug reporters, etc.) |
| **Bug Report Review** | View and respond to user-submitted bug reports and feature requests |
| Crypto Wallet | MetaMask ETH / ERC-20 sends to any address / chain |
| Bank Payouts | Stripe Connect onboarding + biometric-gated bank transfers |
| WebAuthn 2FA | Fingerprint / Face ID required before every financial transfer |
| Transfer Audit Log | Immutable record of all admin transactions |

### 🐛 Bug Reports & Feature Requests
| Feature | Details |
|---|---|
| Submit Feedback | Users can submit bug reports or feature requests from the app |
| Admin Review | Admin can view all reports, update status, and reply |
| Chat-Style Replies | Conversation thread between user and admin |
| Status Tracking | Reports can be marked as open, in_progress, resolved, or closed |

---

## 🖥️ CLI — Terminal Location Tracker

ZTracky includes a powerful command-line interface for terminal enthusiasts. Intuitive, hacker-movie aesthetic.

```bash
# Install CLI
cd cli && pip install -e .

# Commands
ztracky login           # Authenticate
ztracky status          # Show account status
ztracky track           # Real-time tracking dashboard
ztracky friends         # List friends
ztracky locate alice    # Get friend's location
ztracky chat alice      # Chat with friend (premium)
ztracky requests        # Manage friend requests
ztracky submit-bug      # Submit bug report
ztracky premium         # Check premium status
```

---

## 💳 Payment Methods

| Method | Flow |
|---|---|
| **Stripe** | Hosted Checkout session → webhook marks `is_premium` |
| **Ethereum (MetaMask)** | `eth_sendTransaction` → backend verifies → premium granted |
| **Smart Contract** | Deploy `ZTrackySubscription.sol`; users call `subscribe()` directly on-chain |

---

## 📱 SMS Commands (Twilio)

Text these commands to your Twilio number:

| Command | Effect |
|---|---|
| `TRACK +1234567890` | Activates lost mode for that phone number — sends silent deep-link SMS |
| `LOCATE +1234567890` | Replies with last known GPS coordinates + Google Maps link |

---

## 🚀 Quick Start (Docker Compose)

```bash
git clone https://github.com/Zaidux/ZTracky.git
cd ZTracky

# Copy and edit environment variables
cp .env.example .env
# Edit .env: set JWT_SECRET, ADMIN_KEY, TWILIO_SID, STRIPE_SECRET_KEY …

docker compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3001 |
| API (FastAPI) | http://localhost:8000/docs |
| WebSocket Hub | ws://localhost:8001/ws |

---

## 🔧 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `JWT_SECRET` | `ztracky-secret-key-change-in-production` | Sign JWT tokens |
| `ADMIN_KEY` | `ztracky-admin-key-change-me` | Admin API access key |
| `DATABASE_URL` | `sqlite:///./ztracky.db` | SQLAlchemy database URL |
| `GO_SERVICE_URL` | `http://localhost:8001` | Internal URL for Go hub |
| `STRIPE_SECRET_KEY` | *(empty)* | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | *(empty)* | Stripe webhook signing secret |
| `TWILIO_SID` | *(empty)* | Twilio account SID |
| `TWILIO_TOKEN` | *(empty)* | Twilio auth token |
| `TWILIO_FROM` | *(empty)* | Twilio sender phone number |
| `APP_URL` | `http://localhost` | Public URL (used in SMS links) |
| `RP_ID` | `localhost` | WebAuthn relying party ID (your domain) |
| `PREMIUM_PRICE_CENTS` | `999` | Stripe subscription price in cents |
| `OSRM_BASE_URL` | `https://router.project-osrm.org` | OSRM routing server (replace with self-hosted for production) |

---

## 🧪 Running Tests

```bash
# Python (50 tests)
cd backend
pip install -r requirements-test.txt
pytest test_api.py -v

# Go (14 tests)
cd location-service
go test ./... -v
```

---

## 📁 Project Structure

```
ZTracky/
├── backend/                  # Python FastAPI REST API
│   ├── main.py               # All endpoints
│   ├── database.py           # SQLAlchemy models
│   ├── auth.py               # JWT helpers
│   ├── requirements.txt
│   └── test_api.py           # 50 integration tests
├── location-service/         # Go WebSocket hub
│   ├── main.go
│   └── main_test.go          # 14 unit tests
├── frontend/                 # Browser PWA
│   ├── index.html            # Main app
│   ├── app.js                # All frontend logic
│   ├── style.css
│   ├── sw.js                 # Service Worker (offline queuing)
│   ├── admin.html            # Admin panel
│   ├── admin.js
│   └── admin.css
├── cli/                      # Terminal-based client
│   ├── ztracky.py            # CLI application
│   ├── setup.py              # Package setup
│   ├── requirements.txt
│   └── README.md             # CLI documentation
├── contracts/
│   └── ZTrackySubscription.sol   # Solidity smart contract
├── docker-compose.yml
└── DEPLOY.md                 # Deployment guide
```

---

## 🔒 Security Notes

- **No card data** is ever stored — Stripe Checkout handles everything
- **No private keys** — MetaMask signs all blockchain transactions client-side
- **WebAuthn 2FA** gates every admin financial transfer
- **Geofence privacy** — nearby anonymous devices return distance only, never coordinates
- CORS is `allow_origins=["*"]` by default; **change to your domain in production**
