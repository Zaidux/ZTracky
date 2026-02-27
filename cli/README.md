# 🖥️ ZTracky CLI — Terminal Location Tracker

A sleek, intuitive command-line interface for ZTracky that makes location tracking feel like a hacker movie. Real-time friend tracking, chat, and more — all from your terminal.

```
╔═══════════════════════════════════════════════════════════════════════════╗
║ ███████╗████████╗██████╗  █████╗  ██████╗██╗  ██╗██╗   ██╗                ║
║ ╚══███╔╝╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██║ ██╔╝╚██╗ ██╔╝                ║
║   ███╔╝    ██║   ██████╔╝███████║██║     █████╔╝  ╚████╔╝                 ║
║  ███╔╝     ██║   ██╔══██╗██╔══██║██║     ██╔═██╗   ╚██╔╝                  ║
║ ███████╗   ██║   ██║  ██║██║  ██║╚██████╗██║  ██╗   ██║                   ║
║ ╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝   ╚═╝                   ║
╠═══════════════════════════════════════════════════════════════════════════╣
║              Terminal Location Tracker • v2.0.0                           ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

## 🚀 Installation

```bash
cd cli
pip install -r requirements.txt
pip install -e .
```

Or install directly:

```bash
pip install .
```

## 📋 Commands

### Authentication

```bash
# Create a new account
ztracky register

# Log in to your account
ztracky login

# Log out
ztracky logout
```

### Status & Tracking

```bash
# Show your account status
ztracky status

# Start real-time tracking dashboard
ztracky track

# Check premium status
ztracky premium
```

### Friends

```bash
# List all friends
ztracky friends

# Locate a specific friend
ztracky locate alice

# Manage friend requests
ztracky requests
```

### Chat (Premium)

```bash
# Chat with a friend
ztracky chat alice
```

### Feedback

```bash
# Submit a bug report or feature request
ztracky submit-bug
```

## 🎨 Features

- **Intuitive Interface** — Clean, minimal design inspired by hacker movies
- **Real-time Dashboard** — Live-updating friend locations with auto-refresh
- **Rich Output** — Beautiful tables, panels, and colors using Rich
- **Secure Credentials** — Token stored securely in `~/.ztracky/config.json`
- **Full API Support** — All ZTracky features accessible from terminal

## ⚙️ Configuration

Set environment variables to customize:

```bash
# API server URL (default: http://localhost:8000)
export ZTRACKY_API=https://your-server.com

# WebSocket server URL (default: ws://localhost:8001)
export ZTRACKY_WS=wss://your-server.com:8001
```

## 🔧 Requirements

- Python 3.8+
- requests
- rich
- click
- websocket-client

## 📜 License

Part of the ZTracky project. MIT License.
