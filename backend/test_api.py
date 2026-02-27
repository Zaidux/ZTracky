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
