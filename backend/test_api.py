"""
ZTracky Backend – Integration Tests
Run with: pytest test_api.py -v
"""
import pytest
from fastapi.testclient import TestClient

# Ensure we use a fresh in-memory-style DB for tests
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ztracky.db")

from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    """Re-create tables before every test and drop DB file after."""
    from database import Base, engine
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


# ── Helpers ───────────────────────────────────────────────────────────────

def register(username, email, password):
    resp = client.post("/api/register", json={"username": username, "email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def login(username, password):
    resp = client.post("/api/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Auth tests ─────────────────────────────────────────────────────────────

class TestAuth:
    def test_register_success(self):
        data = register("alice", "alice@test.com", "pass123")
        assert data["user"]["username"] == "alice"
        assert data["user"]["id"] == 1
        assert "access_token" in data

    def test_register_duplicate_username(self):
        register("alice", "alice@test.com", "pass123")
        resp = client.post("/api/register", json={"username": "alice", "email": "alice2@test.com", "password": "pass"})
        assert resp.status_code == 400

    def test_register_duplicate_email(self):
        register("alice", "alice@test.com", "pass123")
        resp = client.post("/api/register", json={"username": "alice2", "email": "alice@test.com", "password": "pass"})
        assert resp.status_code == 400

    def test_login_success(self):
        register("alice", "alice@test.com", "pass123")
        data = login("alice", "pass123")
        assert data["user"]["username"] == "alice"
        assert "access_token" in data

    def test_login_wrong_password(self):
        register("alice", "alice@test.com", "pass123")
        resp = client.post("/api/login", data={"username": "alice", "password": "wrong"})
        assert resp.status_code == 400

    def test_get_me(self):
        data = register("alice", "alice@test.com", "pass123")
        resp = client.get("/api/me", headers=auth(data["access_token"]))
        assert resp.status_code == 200
        assert resp.json()["username"] == "alice"

    def test_get_me_no_token(self):
        resp = client.get("/api/me")
        assert resp.status_code == 401

    def test_verify_token(self):
        data = register("alice", "alice@test.com", "pass123")
        resp = client.get("/api/verify-token", headers=auth(data["access_token"]))
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_verify_invalid_token(self):
        resp = client.get("/api/verify-token", headers=auth("not.a.real.token"))
        assert resp.status_code == 401


# ── Tracking Request tests ─────────────────────────────────────────────────

class TestTrackingRequests:
    def setup_users(self):
        alice = register("alice", "alice@test.com", "pass")
        bob = register("bob", "bob@test.com", "pass")
        return alice["access_token"], bob["access_token"], alice["user"]["id"], bob["user"]["id"]

    def test_send_request(self):
        ta, tb, _, _ = self.setup_users()
        resp = client.post("/api/requests/send?username=bob", headers=auth(ta))
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["sender_username"] == "alice"
        assert data["receiver_username"] == "bob"

    def test_send_request_to_self(self):
        ta, _, _, _ = self.setup_users()
        resp = client.post("/api/requests/send?username=alice", headers=auth(ta))
        assert resp.status_code == 400

    def test_send_request_to_nonexistent_user(self):
        ta, _, _, _ = self.setup_users()
        resp = client.post("/api/requests/send?username=ghost", headers=auth(ta))
        assert resp.status_code == 404

    def test_send_duplicate_request(self):
        ta, tb, _, _ = self.setup_users()
        client.post("/api/requests/send?username=bob", headers=auth(ta))
        resp = client.post("/api/requests/send?username=bob", headers=auth(ta))
        assert resp.status_code == 400

    def test_list_requests(self):
        ta, tb, _, _ = self.setup_users()
        client.post("/api/requests/send?username=bob", headers=auth(ta))

        resp_a = client.get("/api/requests", headers=auth(ta))
        resp_b = client.get("/api/requests", headers=auth(tb))
        assert len(resp_a.json()) == 1
        assert len(resp_b.json()) == 1

    def test_accept_request(self):
        ta, tb, _, _ = self.setup_users()
        req = client.post("/api/requests/send?username=bob", headers=auth(ta)).json()
        rid = req["id"]

        resp = client.post(f"/api/requests/{rid}/accept", headers=auth(tb))
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_reject_request(self):
        ta, tb, _, _ = self.setup_users()
        req = client.post("/api/requests/send?username=bob", headers=auth(ta)).json()
        rid = req["id"]

        resp = client.post(f"/api/requests/{rid}/reject", headers=auth(tb))
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_cannot_accept_own_outgoing_request(self):
        ta, tb, _, _ = self.setup_users()
        req = client.post("/api/requests/send?username=bob", headers=auth(ta)).json()
        rid = req["id"]
        # Alice (sender) tries to accept – should fail (only receiver can accept)
        resp = client.post(f"/api/requests/{rid}/accept", headers=auth(ta))
        assert resp.status_code == 404

    def test_list_friends_after_accept(self):
        ta, tb, _, _ = self.setup_users()
        req = client.post("/api/requests/send?username=bob", headers=auth(ta)).json()
        client.post(f"/api/requests/{req['id']}/accept", headers=auth(tb))

        friends_a = client.get("/api/friends", headers=auth(ta)).json()
        friends_b = client.get("/api/friends", headers=auth(tb)).json()
        assert any(f["username"] == "bob" for f in friends_a)
        assert any(f["username"] == "alice" for f in friends_b)

    def test_no_friends_before_accept(self):
        ta, tb, _, _ = self.setup_users()
        client.post("/api/requests/send?username=bob", headers=auth(ta))
        friends_a = client.get("/api/friends", headers=auth(ta)).json()
        assert friends_a == []


# ── Location tests ─────────────────────────────────────────────────────────

class TestLocation:
    def setup_friendship(self):
        alice = register("alice", "alice@test.com", "pass")
        bob = register("bob", "bob@test.com", "pass")
        ta, tb = alice["access_token"], bob["access_token"]
        req = client.post("/api/requests/send?username=bob", headers=auth(ta)).json()
        client.post(f"/api/requests/{req['id']}/accept", headers=auth(tb))
        return ta, tb, alice["user"]["id"], bob["user"]["id"]

    def test_update_my_location(self):
        alice = register("alice", "alice@test.com", "pass")
        ta = alice["access_token"]
        resp = client.post("/api/location",
                           json={"latitude": 40.7128, "longitude": -74.0060, "accuracy": 10.0},
                           headers=auth(ta))
        assert resp.status_code == 200
        data = resp.json()
        assert data["latitude"] == pytest.approx(40.7128)
        assert data["longitude"] == pytest.approx(-74.0060)
        assert data["accuracy"] == pytest.approx(10.0)
        assert data["username"] == "alice"

    def test_update_location_overwrite(self):
        alice = register("alice", "alice@test.com", "pass")
        ta = alice["access_token"]
        client.post("/api/location", json={"latitude": 10.0, "longitude": 20.0}, headers=auth(ta))
        resp = client.post("/api/location", json={"latitude": 51.5, "longitude": -0.1}, headers=auth(ta))
        assert resp.json()["latitude"] == pytest.approx(51.5)

    def test_friend_can_get_my_location(self):
        ta, tb, alice_id, _ = self.setup_friendship()
        client.post("/api/location", json={"latitude": 40.7128, "longitude": -74.006}, headers=auth(ta))
        resp = client.get(f"/api/location/{alice_id}", headers=auth(tb))
        assert resp.status_code == 200
        assert resp.json()["latitude"] == pytest.approx(40.7128)

    def test_stranger_cannot_get_my_location(self):
        ta, tb, alice_id, _ = self.setup_friendship()
        client.post("/api/location", json={"latitude": 40.7128, "longitude": -74.006}, headers=auth(ta))
        eve = register("eve", "eve@test.com", "evil")
        resp = client.get(f"/api/location/{alice_id}", headers=auth(eve["access_token"]))
        assert resp.status_code == 403

    def test_get_friends_locations(self):
        ta, tb, alice_id, bob_id = self.setup_friendship()
        client.post("/api/location", json={"latitude": 51.5, "longitude": -0.1}, headers=auth(tb))
        resp = client.get("/api/friends/locations", headers=auth(ta))
        assert resp.status_code == 200
        locs = resp.json()
        assert any(l["username"] == "bob" for l in locs)

    def test_location_not_available_returns_404(self):
        ta, tb, alice_id, _ = self.setup_friendship()
        # Alice hasn't posted location yet
        resp = client.get(f"/api/location/{alice_id}", headers=auth(tb))
        assert resp.status_code == 404

    def test_get_own_location(self):
        alice = register("alice", "alice@test.com", "pass")
        ta = alice["access_token"]
        alice_id = alice["user"]["id"]
        client.post("/api/location", json={"latitude": 1.0, "longitude": 2.0}, headers=auth(ta))
        resp = client.get(f"/api/location/{alice_id}", headers=auth(ta))
        assert resp.status_code == 200


# ── Geofence tests ────────────────────────────────────────────────────────
class TestGeofences:
    def _setup(self):
        register("alice", "alice@test.com", "pass123")
        tok = login("alice", "pass123")["access_token"]
        return auth(tok)

    def test_create_geofence(self):
        h = self._setup()
        r = client.post("/api/geofences", json={"label": "Home", "latitude": 51.5, "longitude": -0.1, "radius_meters": 100}, headers=h)
        assert r.status_code == 201
        assert r.json()["label"] == "Home"

    def test_list_geofences(self):
        h = self._setup()
        client.post("/api/geofences", json={"label": "Work", "latitude": 40.7, "longitude": -74.0, "radius_meters": 200}, headers=h)
        r = client.get("/api/geofences", headers=h)
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_delete_geofence(self):
        h = self._setup()
        gid = client.post("/api/geofences", json={"label": "Shop", "latitude": 48.8, "longitude": 2.3, "radius_meters": 150}, headers=h).json()["id"]
        r = client.delete(f"/api/geofences/{gid}", headers=h)
        assert r.status_code == 204

    def test_delete_other_users_geofence_fails(self):
        h1 = self._setup()
        register("bob", "bob@test.com", "pass123")
        h2 = auth(login("bob", "pass123")["access_token"])
        gid = client.post("/api/geofences", json={"label": "Home", "latitude": 51.5, "longitude": -0.1}, headers=h1).json()["id"]
        r = client.delete(f"/api/geofences/{gid}", headers=h2)
        assert r.status_code == 404

    def test_geofence_alert_on_location_update(self):
        h = self._setup()
        # Create geofence exactly at (10, 10) radius 100m
        client.post("/api/geofences", json={"label": "Test Zone", "latitude": 10.0, "longitude": 10.0, "radius_meters": 100}, headers=h)
        # Push location inside geofence
        client.post("/api/location", json={"latitude": 10.0, "longitude": 10.0, "accuracy": 5}, headers=h)
        alerts = client.get("/api/geofences/alerts", headers=h).json()
        assert any(a["event_type"] == "enter" for a in alerts)


# ── Chat tests ────────────────────────────────────────────────────────────
class TestChat:
    def _setup_friends(self):
        register("alice", "alice@test.com", "pass123")
        register("bob", "bob@test.com", "pass123")
        ta = login("alice", "pass123")["access_token"]
        tb = login("bob", "pass123")["access_token"]
        ha, hb = auth(ta), auth(tb)
        # Make them friends
        req_id = client.post("/api/requests/send?username=bob", headers=ha).json()["id"]
        client.post(f"/api/requests/{req_id}/accept", headers=hb)
        # Upgrade alice to premium
        ha_admin = {"X-Admin-Key": "ztracky-admin-key-change-me"}
        alice_id = client.get("/api/me", headers=ha).json()["id"]
        client.post(f"/api/admin/users/{alice_id}/upgrade", headers={**ha_admin})
        # Re-login to get fresh token reflecting premium
        ta = login("alice", "pass123")["access_token"]
        ha = auth(ta)
        return ha, hb, client.get("/api/me", headers=hb).json()["id"]

    def test_send_and_receive_message(self):
        ha, hb, bob_id = self._setup_friends()
        alice_id = client.get("/api/me", headers=ha).json()["id"]
        r = client.post(f"/api/chat/{bob_id}", json={"content": "Hello Bob!"}, headers=ha)
        assert r.status_code == 201
        assert r.json()["content"] == "Hello Bob!"
        # Bob can read it
        msgs = client.get(f"/api/chat/{alice_id}", headers=hb).json()
        assert any(m["content"] == "Hello Bob!" for m in msgs)

    def test_chat_requires_premium(self):
        register("alice", "alice@test.com", "pass123")
        register("bob", "bob@test.com", "pass123")
        ha = auth(login("alice", "pass123")["access_token"])
        hb = auth(login("bob", "pass123")["access_token"])
        req_id = client.post("/api/requests/send?username=bob", headers=ha).json()["id"]
        client.post(f"/api/requests/{req_id}/accept", headers=hb)
        bob_id = client.get("/api/me", headers=hb).json()["id"]
        r = client.post(f"/api/chat/{bob_id}", json={"content": "hi"}, headers=ha)
        assert r.status_code == 402

    def test_chat_non_friend_blocked(self):
        register("alice", "alice@test.com", "pass123")
        register("bob", "bob@test.com", "pass123")
        ha = auth(login("alice", "pass123")["access_token"])
        # upgrade
        alice_id = client.get("/api/me", headers=ha).json()["id"]
        client.post(f"/api/admin/users/{alice_id}/upgrade", headers={"X-Admin-Key": "ztracky-admin-key-change-me"})
        ta = login("alice", "pass123")["access_token"]; ha = auth(ta)
        bob_id = client.get("/api/me", headers=auth(login("bob", "pass123")["access_token"])).json()["id"]
        r = client.post(f"/api/chat/{bob_id}", json={"content": "hi"}, headers=ha)
        assert r.status_code == 403

    def test_unread_count(self):
        ha, hb, bob_id = self._setup_friends()
        client.post(f"/api/chat/{bob_id}", json={"content": "ping"}, headers=ha)
        r = client.get("/api/chat/unread/count", headers=hb)
        assert r.status_code == 200
        assert r.json()["unread"] >= 1


# ── Social links tests ────────────────────────────────────────────────────
class TestSocialLinks:
    def test_update_and_read_social_links(self):
        register("alice", "alice@test.com", "pass123")
        register("bob", "bob@test.com", "pass123")
        ha = auth(login("alice", "pass123")["access_token"])
        hb = auth(login("bob", "pass123")["access_token"])
        # Update Alice's social links
        r = client.patch("/api/me/social", json={"linked_whatsapp": "+15551234567", "linked_facebook": "alicefb"}, headers=ha)
        assert r.status_code == 200
        assert r.json()["linked_whatsapp"] == "+15551234567"
        # Make friends
        req_id = client.post("/api/requests/send?username=bob", headers=ha).json()["id"]
        client.post(f"/api/requests/{req_id}/accept", headers=hb)
        alice_id = client.get("/api/me", headers=ha).json()["id"]
        r2 = client.get(f"/api/friends/social/{alice_id}", headers=hb)
        assert r2.status_code == 200
        assert r2.json()["linked_whatsapp"] == "+15551234567"

    def test_social_link_blocked_for_non_friend(self):
        register("alice", "alice@test.com", "pass123")
        register("bob", "bob@test.com", "pass123")
        ha = auth(login("alice", "pass123")["access_token"])
        hb = auth(login("bob", "pass123")["access_token"])
        alice_id = client.get("/api/me", headers=ha).json()["id"]
        r = client.get(f"/api/friends/social/{alice_id}", headers=hb)
        assert r.status_code == 403


# ── Call-Based Tracking tests ─────────────────────────────────────────────
class TestCallTracking:
    """Call-tracking is a premium feature."""

    def _premium_user(self):
        register("alice", "alice@test.com", "pass123")
        h = auth(login("alice", "pass123")["access_token"])
        alice_id = client.get("/api/me", headers=h).json()["id"]
        client.post(f"/api/admin/users/{alice_id}/upgrade",
                    headers={"X-Admin-Key": "ztracky-admin-key-change-me"})
        h = auth(login("alice", "pass123")["access_token"])
        return h

    def test_requires_premium(self):
        register("alice", "alice@test.com", "pass123")
        h = auth(login("alice", "pass123")["access_token"])
        r = client.post("/api/call-tracking", json={"caller_phone": "+15551234567"}, headers=h)
        assert r.status_code == 402

    def test_create_event_without_twilio(self):
        """Without Twilio configured, we still persist a call-tracking event."""
        h = self._premium_user()
        r = client.post("/api/call-tracking", json={"caller_phone": "+15551234567"}, headers=h)
        assert r.status_code == 201
        data = r.json()
        assert data["caller_phone"] == "+15551234567"
        assert "id" in data
        # notes should mention insufficient data when Twilio is absent
        assert data["notes"] is not None

    def test_create_event_with_user_location(self):
        """With a known user location the estimate is anchored to it."""
        h = self._premium_user()
        # Give alice a location
        client.post("/api/location", json={"latitude": 51.5, "longitude": -0.1, "accuracy": 10}, headers=h)
        r = client.post("/api/call-tracking", json={"caller_phone": "+441234567890"}, headers=h)
        assert r.status_code == 201
        data = r.json()
        assert data["caller_phone"] == "+441234567890"

    def test_list_events(self):
        h = self._premium_user()
        client.post("/api/call-tracking", json={"caller_phone": "+15551234567"}, headers=h)
        client.post("/api/call-tracking", json={"caller_phone": "+447911123456"}, headers=h)
        r = client.get("/api/call-tracking", headers=h)
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_list_events_requires_premium(self):
        register("alice", "alice@test.com", "pass123")
        h = auth(login("alice", "pass123")["access_token"])
        r = client.get("/api/call-tracking", headers=h)
        assert r.status_code == 402

    def test_events_isolated_per_user(self):
        """User A's events are not visible to user B."""
        hA = self._premium_user()
        register("bob", "bob@test.com", "pass123")
        hB_free = auth(login("bob", "pass123")["access_token"])
        # Upgrade bob too
        bob_id = client.get("/api/me", headers=hB_free).json()["id"]
        client.post(f"/api/admin/users/{bob_id}/upgrade",
                    headers={"X-Admin-Key": "ztracky-admin-key-change-me"})
        hB = auth(login("bob", "pass123")["access_token"])
        client.post("/api/call-tracking", json={"caller_phone": "+15551234567"}, headers=hA)
        r = client.get("/api/call-tracking", headers=hB)
        assert r.status_code == 200
        assert len(r.json()) == 0   # Bob sees none of Alice's events


# ── Trail Navigation tests ─────────────────────────────────────────────────
class TestNavigation:
    """Navigation is a premium feature requiring friendship + known locations."""

    def _setup(self):
        register("alice", "alice@test.com", "pass123")
        register("bob", "bob@test.com", "pass123")
        hA = auth(login("alice", "pass123")["access_token"])
        hB = auth(login("bob", "pass123")["access_token"])
        # Make friends
        req_id = client.post("/api/requests/send?username=bob", headers=hA).json()["id"]
        client.post(f"/api/requests/{req_id}/accept", headers=hB)
        # Upgrade Alice
        alice_id = client.get("/api/me", headers=hA).json()["id"]
        client.post(f"/api/admin/users/{alice_id}/upgrade",
                    headers={"X-Admin-Key": "ztracky-admin-key-change-me"})
        hA = auth(login("alice", "pass123")["access_token"])
        bob_id = client.get("/api/me", headers=hB).json()["id"]
        return hA, hB, bob_id

    def test_requires_premium(self):
        register("alice", "alice@test.com", "pass123")
        register("bob", "bob@test.com", "pass123")
        hA = auth(login("alice", "pass123")["access_token"])
        hB = auth(login("bob", "pass123")["access_token"])
        req_id = client.post("/api/requests/send?username=bob", headers=hA).json()["id"]
        client.post(f"/api/requests/{req_id}/accept", headers=hB)
        bob_id = client.get("/api/me", headers=hB).json()["id"]
        r = client.get(f"/api/navigate/{bob_id}", headers=hA)
        assert r.status_code == 402

    def test_requires_friendship(self):
        hA, hB, bob_id = self._setup()
        register("carol", "carol@test.com", "pass123")
        hC_free = auth(login("carol", "pass123")["access_token"])
        carol_id = client.get("/api/me", headers=hC_free).json()["id"]
        client.post(f"/api/admin/users/{carol_id}/upgrade",
                    headers={"X-Admin-Key": "ztracky-admin-key-change-me"})
        hC = auth(login("carol", "pass123")["access_token"])
        r = client.get(f"/api/navigate/{bob_id}", headers=hC)
        assert r.status_code == 403

    def test_requires_own_location(self):
        hA, hB, bob_id = self._setup()
        # Bob has a location but Alice does not
        client.post("/api/location", json={"latitude": 51.5, "longitude": -0.1}, headers=hB)
        r = client.get(f"/api/navigate/{bob_id}", headers=hA)
        assert r.status_code == 400

    def test_requires_friend_location(self):
        hA, hB, bob_id = self._setup()
        # Alice has a location but Bob does not
        client.post("/api/location", json={"latitude": 51.5, "longitude": -0.1}, headers=hA)
        r = client.get(f"/api/navigate/{bob_id}", headers=hA)
        assert r.status_code == 404

    def test_same_location_returns_trivial(self):
        hA, hB, bob_id = self._setup()
        # Same coordinates → trivial result, no OSRM call needed
        client.post("/api/location", json={"latitude": 51.5, "longitude": -0.1}, headers=hA)
        client.post("/api/location", json={"latitude": 51.5, "longitude": -0.1}, headers=hB)
        r = client.get(f"/api/navigate/{bob_id}", headers=hA)
        assert r.status_code == 200
        data = r.json()
        assert data["distance_meters"] == 0

    def test_different_locations_returns_route(self):
        """OSRM may be unavailable in test env — graceful fallback is acceptable."""
        hA, hB, bob_id = self._setup()
        # London → Manchester (about 270 km straight-line)
        client.post("/api/location", json={"latitude": 51.5, "longitude": -0.12}, headers=hA)
        client.post("/api/location", json={"latitude": 53.5, "longitude": -2.24}, headers=hB)
        r = client.get(f"/api/navigate/{bob_id}?mode=driving", headers=hA)
        assert r.status_code == 200
        data = r.json()
        assert data["distance_meters"] > 0
        assert len(data["geometry"]) >= 2
        assert len(data["steps"]) >= 1
        assert data["mode"] == "driving"
        assert "friend_username" in data

    def test_avoid_highways_mode(self):
        hA, hB, bob_id = self._setup()
        client.post("/api/location", json={"latitude": 51.5, "longitude": -0.12}, headers=hA)
        client.post("/api/location", json={"latitude": 53.5, "longitude": -2.24}, headers=hB)
        r = client.get(f"/api/navigate/{bob_id}?mode=driving&avoid_highways=true", headers=hA)
        assert r.status_code == 200
        assert r.json()["avoid_highways"] is True
