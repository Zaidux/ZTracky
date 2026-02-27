#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════╗
║                    ZTracky CLI — Terminal Location Tracker                 ║
║                   Real-time tracking from your command line                ║
╚═══════════════════════════════════════════════════════════════════════════╝

Usage:
    ztracky login                       - Authenticate with ZTracky
    ztracky status                      - Show current tracking status
    ztracky track                       - Start real-time tracking mode
    ztracky friends                     - List your friends
    ztracky locate <username>           - Get a friend's location
    ztracky chat <username>             - Chat with a friend
    ztracky requests                    - Manage friend requests
    ztracky submit-bug                  - Submit a bug report
    ztracky premium                     - Check premium status
    ztracky logout                      - Clear saved credentials

The aesthetic is inspired by hacker movies — clean, minimal, and powerful.
"""

import os
import sys
import json
import time
import threading
import signal
from pathlib import Path
from datetime import datetime
from typing import Optional

try:
    import click
    import requests
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.live import Live
    from rich.layout import Layout
    from rich.text import Text
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.markdown import Markdown
    from rich.prompt import Prompt, Confirm
except ImportError:
    print("Missing dependencies. Install with: pip install -r requirements.txt")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

CONFIG_DIR = Path.home() / ".ztracky"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_API = "http://localhost:8000"
DEFAULT_WS = "ws://localhost:8001"

console = Console()


def get_api_base():
    """Get API base URL from environment or config."""
    return os.environ.get("ZTRACKY_API", DEFAULT_API)


def get_ws_base():
    """Get WebSocket base URL from environment or config."""
    return os.environ.get("ZTRACKY_WS", DEFAULT_WS)


# ═══════════════════════════════════════════════════════════════════════════
# Credential Management
# ═══════════════════════════════════════════════════════════════════════════

def load_config() -> dict:
    """Load saved configuration and credentials."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def save_config(config: dict):
    """Save configuration and credentials."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    os.chmod(CONFIG_FILE, 0o600)  # Secure the credentials file


def get_token() -> Optional[str]:
    """Get saved authentication token."""
    return load_config().get("token")


def get_user() -> Optional[dict]:
    """Get saved user info."""
    return load_config().get("user")


def clear_credentials():
    """Clear saved credentials."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()


# ═══════════════════════════════════════════════════════════════════════════
# API Client
# ═══════════════════════════════════════════════════════════════════════════

def api_headers():
    """Get API headers with authentication."""
    token = get_token()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def api_get(endpoint: str) -> dict:
    """Make authenticated GET request."""
    try:
        resp = requests.get(f"{get_api_base()}{endpoint}", headers=api_headers(), timeout=10)
        return resp.json() if resp.ok else {"error": resp.json().get("detail", "Request failed")}
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot connect to ZTracky server"}
    except Exception as e:
        return {"error": str(e)}


def api_post(endpoint: str, data: dict = None) -> dict:
    """Make authenticated POST request."""
    try:
        resp = requests.post(
            f"{get_api_base()}{endpoint}",
            headers=api_headers(),
            json=data,
            timeout=10
        )
        return resp.json() if resp.ok else {"error": resp.json().get("detail", "Request failed")}
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot connect to ZTracky server"}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# Display Helpers
# ═══════════════════════════════════════════════════════════════════════════

def print_banner():
    """Print the ZTracky banner."""
    banner = """
[bold cyan]╔═══════════════════════════════════════════════════════════════════════════╗
║[/bold cyan] [bold white]███████╗[/bold white][bold green]████████╗[/bold green][bold yellow]██████╗ [/bold yellow][bold red] █████╗ [/bold red][bold magenta] ██████╗[/bold magenta][bold blue]██╗  ██╗[/bold blue][bold cyan]██╗   ██╗[/bold cyan] [bold cyan]║[/bold cyan]
[bold cyan]║[/bold cyan] [bold white]╚══███╔╝[/bold white][bold green]╚══██╔══╝[/bold green][bold yellow]██╔══██╗[/bold yellow][bold red]██╔══██╗[/bold red][bold magenta]██╔════╝[/bold magenta][bold blue]██║ ██╔╝[/bold blue][bold cyan]╚██╗ ██╔╝[/bold cyan] [bold cyan]║[/bold cyan]
[bold cyan]║[/bold cyan] [bold white]  ███╔╝ [/bold white][bold green]   ██║   [/bold green][bold yellow]██████╔╝[/bold yellow][bold red]███████║[/bold red][bold magenta]██║     [/bold magenta][bold blue]█████╔╝ [/bold blue][bold cyan] ╚████╔╝ [/bold cyan] [bold cyan]║[/bold cyan]
[bold cyan]║[/bold cyan] [bold white] ███╔╝  [/bold white][bold green]   ██║   [/bold green][bold yellow]██╔══██╗[/bold yellow][bold red]██╔══██║[/bold red][bold magenta]██║     [/bold magenta][bold blue]██╔═██╗ [/bold blue][bold cyan]  ╚██╔╝  [/bold cyan] [bold cyan]║[/bold cyan]
[bold cyan]║[/bold cyan] [bold white]███████╗[/bold white][bold green]   ██║   [/bold green][bold yellow]██║  ██║[/bold yellow][bold red]██║  ██║[/bold red][bold magenta]╚██████╗[/bold magenta][bold blue]██║  ██╗[/bold blue][bold cyan]   ██║   [/bold cyan] [bold cyan]║[/bold cyan]
[bold cyan]║[/bold cyan] [bold white]╚══════╝[/bold white][bold green]   ╚═╝   [/bold green][bold yellow]╚═╝  ╚═╝[/bold yellow][bold red]╚═╝  ╚═╝[/bold red][bold magenta] ╚═════╝[/bold magenta][bold blue]╚═╝  ╚═╝[/bold blue][bold cyan]   ╚═╝   [/bold cyan] [bold cyan]║[/bold cyan]
[bold cyan]╠═══════════════════════════════════════════════════════════════════════════╣[/bold cyan]
[bold cyan]║[/bold cyan]              [dim]Terminal Location Tracker • v2.0.0[/dim]                       [bold cyan]║[/bold cyan]
[bold cyan]╚═══════════════════════════════════════════════════════════════════════════╝[/bold cyan]
"""
    console.print(banner)


def print_error(msg: str):
    """Print error message."""
    console.print(f"[bold red]✗[/bold red] {msg}")


def print_success(msg: str):
    """Print success message."""
    console.print(f"[bold green]✓[/bold green] {msg}")


def print_info(msg: str):
    """Print info message."""
    console.print(f"[bold cyan]ℹ[/bold cyan] {msg}")


def require_auth(func):
    """Decorator to require authentication."""
    import functools
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not get_token():
            print_error("Not authenticated. Run [bold]ztracky login[/bold] first.")
            sys.exit(1)
        return func(*args, **kwargs)
    return wrapper


# ═══════════════════════════════════════════════════════════════════════════
# CLI Commands
# ═══════════════════════════════════════════════════════════════════════════

@click.group()
@click.version_option(version="2.0.0")
def cli():
    """ZTracky — Terminal Location Tracker
    
    Real-time location sharing from your command line.
    """
    pass


@cli.command()
@click.option("--api-key", "-k", default=None, help="Authenticate using an API key instead of password")
def login(api_key):
    """Authenticate with ZTracky server.
    
    Use --api-key to authenticate with an API key (recommended).
    Generate API keys in the web app under Settings > API Keys after setting up 2FA.
    """
    print_banner()
    
    console.print("\n[bold cyan]▸ LOGIN[/bold cyan]\n")
    
    if api_key:
        # API key authentication
        console.print("[dim]Authenticating with API key...[/dim]")
        with console.status("[bold green]Connecting to ZTracky...[/bold green]"):
            resp = requests.post(
                f"{get_api_base()}/api/login/api-key",
                headers={"X-API-Key": api_key},
                timeout=10
            )
        
        if resp.ok:
            data = resp.json()
            save_config({
                "token": data["access_token"],
                "user": data["user"],
                "api_base": get_api_base(),
                "auth_method": "api_key",
                "key_scopes": data.get("key_scopes", ""),
            })
            print_success(f"Welcome back, [bold]{data['user']['username']}[/bold]!")
            console.print(f"[dim]Scopes: {data.get('key_scopes', 'all')}[/dim]")
            
            if data["user"].get("is_premium"):
                console.print("[yellow]⭐ Premium account[/yellow]")
        else:
            print_error("Login failed: " + resp.json().get("detail", "Invalid API key"))
    else:
        # Password authentication (fallback)
        console.print("[dim]Tip: Use [bold]ztracky login --api-key YOUR_KEY[/bold] for API key auth (recommended)[/dim]\n")
        
        username = Prompt.ask("[cyan]Username[/cyan]")
        password = Prompt.ask("[cyan]Password[/cyan]", password=True)
        
        with console.status("[bold green]Connecting to ZTracky...[/bold green]"):
            resp = requests.post(
                f"{get_api_base()}/api/login",
                data={"username": username, "password": password},
                timeout=10
            )
        
        if resp.ok:
            data = resp.json()
            save_config({
                "token": data["access_token"],
                "user": data["user"],
                "api_base": get_api_base(),
                "auth_method": "password",
            })
            print_success(f"Welcome back, [bold]{data['user']['username']}[/bold]!")
            
            if data["user"].get("is_premium"):
                console.print("[yellow]⭐ Premium account[/yellow]")
        else:
            print_error("Login failed: " + resp.json().get("detail", "Invalid credentials"))


@cli.command()
def logout():
    """Clear saved credentials."""
    clear_credentials()
    print_success("Logged out successfully.")


@cli.command()
@require_auth
def status():
    """Show current tracking status and user info."""
    print_banner()
    
    user = get_user()
    config = load_config()
    console.print("\n[bold cyan]▸ STATUS[/bold cyan]\n")
    
    # User info
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value", style="bold")
    
    table.add_row("User", user.get("username", "Unknown"))
    table.add_row("Email", user.get("email", "Unknown"))
    table.add_row("Premium", "[green]✓ Active[/green]" if user.get("is_premium") else "[dim]Free Plan[/dim]")
    auth_method = config.get("auth_method", "password")
    table.add_row("Auth", "[green]🔑 API Key[/green]" if auth_method == "api_key" else "[dim]Password[/dim]")
    if auth_method == "api_key" and config.get("key_scopes"):
        table.add_row("Scopes", config["key_scopes"])
    table.add_row("Server", get_api_base())
    
    console.print(Panel(table, title="[bold]Account[/bold]", border_style="cyan"))
    
    # Friends count
    friends = api_get("/api/friends")
    if not friends.get("error"):
        console.print(f"\n[cyan]Friends:[/cyan] {len(friends)}")
    
    # Location
    loc = api_get(f"/api/location/{user.get('id')}")
    if not loc.get("error"):
        console.print(f"[cyan]Last Location:[/cyan] {loc['latitude']:.6f}, {loc['longitude']:.6f}")
        console.print(f"[dim]Updated: {loc.get('updated_at', 'Unknown')}[/dim]")


@cli.command()
@require_auth
def friends():
    """List your friends."""
    print_banner()
    console.print("\n[bold cyan]▸ FRIENDS[/bold cyan]\n")
    
    with console.status("[bold green]Loading friends...[/bold green]"):
        data = api_get("/api/friends")
    
    if data.get("error"):
        print_error(data["error"])
        return
    
    if not data:
        console.print("[dim]No friends yet. Use [bold]ztracky requests[/bold] to manage friend requests.[/dim]")
        return
    
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim")
    table.add_column("Username", style="bold")
    table.add_column("Email", style="dim")
    table.add_column("Status", justify="center")
    
    for friend in data:
        # Try to get their location to show online status
        loc = api_get(f"/api/location/{friend['id']}")
        status = "[green]● Online[/green]" if not loc.get("error") else "[dim]○ Offline[/dim]"
        table.add_row(str(friend["id"]), friend["username"], friend["email"], status)
    
    console.print(table)


@cli.command()
@click.argument("username")
@require_auth
def locate(username):
    """Get a friend's location."""
    print_banner()
    console.print(f"\n[bold cyan]▸ LOCATE: {username}[/bold cyan]\n")
    
    # Find friend by username
    friends_list = api_get("/api/friends")
    if friends_list.get("error"):
        print_error(friends_list["error"])
        return
    
    friend = next((f for f in friends_list if f["username"] == username), None)
    if not friend:
        print_error(f"User '{username}' is not in your friends list.")
        return
    
    with console.status(f"[bold green]Locating {username}...[/bold green]"):
        loc = api_get(f"/api/location/{friend['id']}")
    
    if loc.get("error"):
        print_error(f"Location unavailable: {loc['error']}")
        return
    
    # Display location
    console.print(Panel(f"""
[bold green]📍 COORDINATES[/bold green]
   Latitude:  [bold]{loc['latitude']:.6f}[/bold]
   Longitude: [bold]{loc['longitude']:.6f}[/bold]
   Accuracy:  {loc.get('accuracy', 'Unknown')} meters

[dim]Last updated: {loc.get('updated_at', 'Unknown')}[/dim]

[cyan]🗺  Google Maps:[/cyan]
   https://www.google.com/maps?q={loc['latitude']},{loc['longitude']}
""", title=f"[bold]{username}'s Location[/bold]", border_style="green"))


@cli.command()
@require_auth
def requests():
    """Manage friend requests."""
    print_banner()
    console.print("\n[bold cyan]▸ FRIEND REQUESTS[/bold cyan]\n")
    
    user = get_user()
    with console.status("[bold green]Loading requests...[/bold green]"):
        data = api_get("/api/requests")
    
    if data.get("error"):
        print_error(data["error"])
        return
    
    # Split into incoming and outgoing
    incoming = [r for r in data if r["receiver_id"] == user["id"] and r["status"] == "pending"]
    outgoing = [r for r in data if r["sender_id"] == user["id"]]
    
    # Incoming requests
    console.print("[bold yellow]Incoming Requests[/bold yellow]")
    if incoming:
        for req in incoming:
            console.print(f"  [cyan]•[/cyan] From [bold]{req['sender_username']}[/bold] — {req['created_at'][:10]}")
            if Confirm.ask(f"    Accept request from {req['sender_username']}?"):
                result = api_post(f"/api/requests/{req['id']}/accept", {})
                if result.get("error"):
                    print_error(result["error"])
                else:
                    print_success(f"Now friends with {req['sender_username']}!")
    else:
        console.print("  [dim]No pending requests[/dim]")
    
    # Outgoing requests
    console.print("\n[bold yellow]Sent Requests[/bold yellow]")
    if outgoing:
        for req in outgoing:
            status_icon = {"pending": "⏳", "accepted": "✓", "rejected": "✗"}
            status_color = {"pending": "yellow", "accepted": "green", "rejected": "red"}
            console.print(
                f"  [{status_color.get(req['status'], 'white')}]"
                f"{status_icon.get(req['status'], '?')}[/{status_color.get(req['status'], 'white')}] "
                f"To [bold]{req['receiver_username']}[/bold] — {req['status']}"
            )
    else:
        console.print("  [dim]No sent requests[/dim]")
    
    # Send new request
    console.print("")
    if Confirm.ask("Send a new friend request?"):
        target = Prompt.ask("Enter username")
        result = api_post(f"/api/requests/send?username={target}", None)
        if result.get("error"):
            print_error(result["error"])
        else:
            print_success(f"Request sent to {target}!")


@cli.command("chat")
@click.argument("username")
@require_auth
def chat_cmd(username):
    """Chat with a friend."""
    print_banner()
    console.print(f"\n[bold cyan]▸ CHAT: {username}[/bold cyan]\n")
    
    user = get_user()
    if not user.get("is_premium"):
        print_info("Chat is a premium feature. You can read messages but need Premium to send.")
    
    # Find friend
    friends_list = api_get("/api/friends")
    if friends_list.get("error"):
        print_error(friends_list["error"])
        return
    
    friend = next((f for f in friends_list if f["username"] == username), None)
    if not friend:
        print_error(f"User '{username}' is not in your friends list.")
        return
    
    # Load and display messages
    messages = api_get(f"/api/chat/{friend['id']}")
    if messages.get("error"):
        print_error(messages["error"])
        return
    
    console.print(f"[dim]──────────────────────────────────────────[/dim]")
    for msg in messages[-20:]:  # Show last 20 messages
        is_mine = msg["sender_id"] == user["id"]
        style = "green" if is_mine else "cyan"
        sender = "You" if is_mine else msg.get("sender_username", "Friend")
        time_str = msg["created_at"][11:16] if len(msg["created_at"]) > 16 else ""
        console.print(f"[{style}]{sender}[/{style}] [dim]{time_str}[/dim]")
        console.print(f"  {msg['content']}")
    console.print(f"[dim]──────────────────────────────────────────[/dim]")
    
    # Send message prompt
    if user.get("is_premium"):
        while True:
            message = Prompt.ask("\n[cyan]Message[/cyan] (or 'q' to quit)")
            if message.lower() == 'q':
                break
            result = api_post(f"/api/chat/{friend['id']}", {"content": message})
            if result.get("error"):
                print_error(result["error"])
            else:
                print_success("Message sent!")


@cli.command("submit-bug")
@require_auth
def submit_bug():
    """Submit a bug report or feature request."""
    print_banner()
    console.print("\n[bold cyan]▸ SUBMIT FEEDBACK[/bold cyan]\n")
    
    report_type = Prompt.ask(
        "Report type",
        choices=["bug", "feature"],
        default="bug"
    )
    title = Prompt.ask("Title")
    console.print("[dim]Enter description (press Enter twice on empty lines to finish):[/dim]")
    
    lines = []
    empty_line_count = 0
    while True:
        line = input()
        if not line:
            empty_line_count += 1
            if empty_line_count >= 2:
                # Two consecutive empty lines ends input
                break
            lines.append(line)
        else:
            empty_line_count = 0
            lines.append(line)
    
    # Remove trailing empty lines
    while lines and not lines[-1]:
        lines.pop()
    description = "\n".join(lines).strip()
    
    if not description:
        print_error("Description cannot be empty.")
        return
    
    with console.status("[bold green]Submitting...[/bold green]"):
        result = api_post("/api/bug-reports", {
            "report_type": report_type,
            "title": title,
            "description": description,
        })
    
    if result.get("error"):
        print_error(result["error"])
    else:
        print_success(f"Feedback submitted! Report ID: {result['id']}")


@cli.command()
@require_auth  
def premium():
    """Check premium status."""
    print_banner()
    console.print("\n[bold cyan]▸ PREMIUM STATUS[/bold cyan]\n")
    
    user = get_user()
    
    if user.get("is_premium"):
        console.print(Panel("""
[bold yellow]⭐ PREMIUM ACTIVE[/bold yellow]

All features unlocked:
  • Location History & Route Playback
  • Priority GPS Updates (10s interval)
  • Unlimited Friends
  • In-App Chat
  • Geofence Alerts
  • Call-Based Tracking
  • Trail Navigation
  • Nearby Phones Detection
""", border_style="yellow"))
    else:
        console.print(Panel("""
[dim]🔒 FREE PLAN[/dim]

Upgrade to Premium for:
  • Location History & Route Playback
  • Priority GPS Updates
  • Unlimited Friends
  • In-App Chat
  • And more...

Visit the web app to subscribe: $9.99/month
""", border_style="dim"))


@cli.command()
@require_auth
def track():
    """Start real-time tracking mode (interactive dashboard)."""
    print_banner()
    console.print("\n[bold cyan]▸ REAL-TIME TRACKING MODE[/bold cyan]")
    console.print("[dim]Press Ctrl+C to exit[/dim]\n")
    
    user = get_user()
    stop_event = threading.Event()
    
    def signal_handler(sig, frame):
        stop_event.set()
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        while not stop_event.is_set():
            # Get friends and their locations
            friends_list = api_get("/api/friends")
            
            console.clear()
            print_banner()
            console.print(f"\n[bold cyan]▸ TRACKING DASHBOARD[/bold cyan] [dim]— {datetime.now().strftime('%H:%M:%S')}[/dim]\n")
            
            if friends_list.get("error"):
                print_error(friends_list["error"])
            elif not friends_list:
                console.print("[dim]No friends to track. Add some friends first![/dim]")
            else:
                table = Table(show_header=True, header_style="bold cyan", box=None)
                table.add_column("User", style="bold")
                table.add_column("Latitude")
                table.add_column("Longitude")
                table.add_column("Accuracy")
                table.add_column("Updated")
                table.add_column("Status")
                
                for friend in friends_list:
                    loc = api_get(f"/api/location/{friend['id']}")
                    if loc.get("error"):
                        table.add_row(
                            friend["username"],
                            "—", "—", "—", "—",
                            "[dim]Offline[/dim]"
                        )
                    else:
                        updated = loc.get("updated_at", "")
                        if updated:
                            updated = updated[11:19]  # Extract time
                        table.add_row(
                            friend["username"],
                            f"{loc['latitude']:.6f}",
                            f"{loc['longitude']:.6f}",
                            f"{loc.get('accuracy', '?')}m",
                            updated,
                            "[green]● Live[/green]"
                        )
                
                console.print(table)
            
            console.print("\n[dim]Refreshing in 5s... (Ctrl+C to exit)[/dim]")
            time.sleep(5)
    
    except KeyboardInterrupt:
        pass
    
    console.print("\n[cyan]Tracking stopped.[/cyan]")


@cli.command()
def register():
    """Create a new ZTracky account."""
    print_banner()
    console.print("\n[bold cyan]▸ REGISTER[/bold cyan]\n")
    
    username = Prompt.ask("[cyan]Username[/cyan]")
    email = Prompt.ask("[cyan]Email[/cyan]")
    password = Prompt.ask("[cyan]Password[/cyan]", password=True)
    confirm = Prompt.ask("[cyan]Confirm Password[/cyan]", password=True)
    
    if password != confirm:
        print_error("Passwords do not match.")
        return
    
    with console.status("[bold green]Creating account...[/bold green]"):
        resp = requests.post(
            f"{get_api_base()}/api/register",
            json={"username": username, "email": email, "password": password},
            timeout=10
        )
    
    if resp.ok:
        data = resp.json()
        save_config({
            "token": data["access_token"],
            "user": data["user"],
            "api_base": get_api_base(),
        })
        print_success(f"Account created! Welcome, [bold]{username}[/bold]!")
    else:
        print_error("Registration failed: " + resp.json().get("detail", "Unknown error"))


@cli.command()
def version():
    """Show version information."""
    console.print(Panel("""
[bold cyan]ZTracky CLI[/bold cyan] v2.0.0

Terminal Location Tracker
Part of the ZTracky suite

[dim]https://github.com/Zaidux/ZTracky[/dim]
""", border_style="cyan"))


# ═══════════════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cli()
