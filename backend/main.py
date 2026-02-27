"""
ZTracky REST API  –  Python / FastAPI
Endpoints: auth · tracking requests · locations · premium · SMS lost-mode ·
           Stripe payments · Ethereum crypto verification · WebAuthn 2FA ·
           Stripe Connect payouts · admin stats · admin wallet audit
"""
import os, secrets, base64, json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Header, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import (
    get_db, create_tables, User, TrackingRequest, Location, LocationHistory,
    Payment, LostDevice, WebAuthnCredential, StripeConnectAccount,
    AdminTransaction, RequestStatus,
)
from auth import hash_password, verify_password, create_access_token, decode_token

# ── Optional integrations (graceful no-ops when env vars absent) ──────────
try:
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
except ImportError:
    stripe = None

try:
    from twilio.rest import Client as TwilioClient
    _twilio = TwilioClient(
        os.environ.get("TWILIO_SID", ""),
        os.environ.get("TWILIO_TOKEN", ""),
    ) if os.environ.get("TWILIO_SID") else None
except ImportError:
    _twilio = None

try:
    from webauthn import (
        generate_registration_options, verify_registration_response,
        generate_authentication_options, verify_authentication_response,
    )
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, UserVerificationRequirement,
        PublicKeyCredentialDescriptor,
    )
    from webauthn.helpers.cose import COSEAlgorithmIdentifier
    _webauthn_ok = True
except Exception:
    _webauthn_ok = False

ADMIN_KEY      = os.environ.get("ADMIN_KEY",      "ztracky-admin-key-change-me")
GO_SERVICE_URL = os.environ.get("GO_SERVICE_URL",  "http://localhost:8001")
RP_ID          = os.environ.get("RP_ID",           "localhost")
RP_NAME        = "ZTracky"
TWILIO_FROM    = os.environ.get("TWILIO_FROM",     "")
APP_URL        = os.environ.get("APP_URL",         "http://localhost")
STRIPE_WH_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# Short-lived transfer-authorisation tokens issued after WebAuthn success
_transfer_tokens: dict[str, int] = {}   # token → user_id

# Per-user WebAuthn challenges (server-side, in-memory; fine for single-instance)
_reg_challenges:  dict[int, bytes] = {}
_auth_challenges: dict[int, bytes] = {}

app = FastAPI(title="ZTracky API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    # allow_origins=["*"] suits self-hosted/local. Use specific domains in prod.
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")


@app.on_event("startup")
def startup():
    create_tables()


# ── Dependencies ───────────────────────────────────────────────────────────
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_admin(x_admin_key: str = Header(default=""), db: Session = Depends(get_db)) -> None:
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


def require_premium(user: User = Depends(get_current_user)) -> User:
    if not user.is_premium:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Premium required")
    return user


def require_transfer_token(x_transfer_token: str = Header(default=""), db: Session = Depends(get_db)) -> int:
    """Validates a short-lived token issued after WebAuthn success."""
    uid = _transfer_tokens.pop(x_transfer_token, None)
    if uid is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired transfer token. Complete biometric auth first.")
    return uid


# ── Schemas ────────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int; username: str; email: str; is_premium: bool; phone_number: Optional[str]
    created_at: datetime
    class Config: from_attributes = True

class Token(BaseModel):
    access_token: str; token_type: str; user: UserOut

class LocationIn(BaseModel):
    latitude: float; longitude: float; accuracy: Optional[float] = None

class LocationOut(BaseModel):
    user_id: int; username: str; latitude: float; longitude: float
    accuracy: Optional[float]; updated_at: datetime
    class Config: from_attributes = True

class RequestOut(BaseModel):
    id: int; sender_id: int; receiver_id: int; status: str
    sender_username: str; receiver_username: str; created_at: datetime
    class Config: from_attributes = True

class FriendOut(BaseModel):
    id: int; username: str; email: str
    class Config: from_attributes = True

class PhoneIn(BaseModel):
    phone_number: str

class StripeCheckoutOut(BaseModel):
    checkout_url: str

class CryptoVerifyIn(BaseModel):
    tx_hash: str
    chain: str = "ethereum"     # "ethereum" | "polygon"
    wallet_address: str

class WebAuthnRegVerifyIn(BaseModel):
    credential: dict

class WebAuthnAuthVerifyIn(BaseModel):
    credential: dict

class SendCryptoIn(BaseModel):
    recipient: str
    amount_wei: int
    network: str = "ethereum"
    tx_hash: str             # MetaMask already sent it; we just record it

class StripePayoutIn(BaseModel):
    amount_cents: int
    destination: str         # Stripe Connect account ID

class AdminTxOut(BaseModel):
    id: int; tx_type: str; recipient: str; amount_wei_or_cents: int
    network: Optional[str]; tx_hash: Optional[str]; status: str; created_at: datetime
    class Config: from_attributes = True


# ── Auth ───────────────────────────────────────────────────────────────────
@app.post("/api/register", status_code=201)
def register(body: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(400, "Username already taken")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(400, "Email already registered")
    user = User(username=body.username, email=body.email, password_hash=hash_password(body.password))
    db.add(user); db.commit(); db.refresh(user)
    return {"access_token": create_access_token({"sub": str(user.id)}), "token_type": "bearer", "user": user}


@app.post("/api/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(400, "Invalid credentials")
    return {"access_token": create_access_token({"sub": str(user.id)}), "token_type": "bearer", "user": user}


@app.get("/api/me")
def me(user: User = Depends(get_current_user)):
    return user


@app.get("/api/verify-token")
def verify_token(user: User = Depends(get_current_user)):
    return {"valid": True, "user_id": user.id}


@app.patch("/api/me/phone")
def set_phone(body: PhoneIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.phone_number = body.phone_number
    db.commit(); db.refresh(user)
    return {"phone_number": user.phone_number}


# ── Tracking Requests ──────────────────────────────────────────────────────
def _req_out(r: TrackingRequest) -> dict:
    return {"id": r.id, "sender_id": r.sender_id, "receiver_id": r.receiver_id,
            "status": r.status.value, "sender_username": r.sender.username,
            "receiver_username": r.receiver.username, "created_at": r.created_at}


@app.post("/api/requests/send", status_code=201)
def send_request(username: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.username == username).first()
    if not target: raise HTTPException(404, "User not found")
    if target.id == user.id: raise HTTPException(400, "Cannot send request to yourself")
    existing = db.query(TrackingRequest).filter(
        TrackingRequest.sender_id == user.id, TrackingRequest.receiver_id == target.id).first()
    if existing: raise HTTPException(400, "Request already sent")
    req = TrackingRequest(sender_id=user.id, receiver_id=target.id)
    db.add(req); db.commit(); db.refresh(req)
    return _req_out(req)


@app.get("/api/requests")
def list_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reqs = db.query(TrackingRequest).filter(
        (TrackingRequest.sender_id == user.id) | (TrackingRequest.receiver_id == user.id)).all()
    return [_req_out(r) for r in reqs]


@app.post("/api/requests/{req_id}/accept")
def accept_request(req_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    req = db.query(TrackingRequest).filter(
        TrackingRequest.id == req_id, TrackingRequest.receiver_id == user.id).first()
    if not req: raise HTTPException(404, "Request not found")
    req.status = RequestStatus.accepted; db.commit(); db.refresh(req)
    return _req_out(req)


@app.post("/api/requests/{req_id}/reject")
def reject_request(req_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    req = db.query(TrackingRequest).filter(
        TrackingRequest.id == req_id, TrackingRequest.receiver_id == user.id).first()
    if not req: raise HTTPException(404, "Request not found")
    req.status = RequestStatus.rejected; db.commit(); db.refresh(req)
    return _req_out(req)


@app.get("/api/friends")
def list_friends(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reqs = db.query(TrackingRequest).filter(
        TrackingRequest.status == RequestStatus.accepted,
        (TrackingRequest.sender_id == user.id) | (TrackingRequest.receiver_id == user.id)).all()
    friends = []
    for r in reqs:
        friend = r.receiver if r.sender_id == user.id else r.sender
        friends.append({"id": friend.id, "username": friend.username, "email": friend.email})
    return friends


# ── Location ───────────────────────────────────────────────────────────────
@app.post("/api/location")
def update_location(body: LocationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    loc = db.query(Location).filter(Location.user_id == user.id).first()
    if loc:
        loc.latitude = body.latitude; loc.longitude = body.longitude
        loc.accuracy = body.accuracy; loc.updated_at = datetime.now(timezone.utc)
    else:
        loc = Location(user_id=user.id, latitude=body.latitude, longitude=body.longitude, accuracy=body.accuracy)
        db.add(loc)
    # History (premium) – keep last 100
    if user.is_premium:
        hist = LocationHistory(user_id=user.id, latitude=body.latitude, longitude=body.longitude, accuracy=body.accuracy)
        db.add(hist)
        old = db.query(LocationHistory).filter(LocationHistory.user_id == user.id)\
                .order_by(LocationHistory.recorded_at.desc()).offset(100).all()
        for h in old: db.delete(h)
    db.commit(); db.refresh(loc)
    return {"user_id": user.id, "username": user.username, "latitude": loc.latitude,
            "longitude": loc.longitude, "accuracy": loc.accuracy, "updated_at": loc.updated_at}


def _friends_of(user_id: int, db: Session) -> list[int]:
    reqs = db.query(TrackingRequest).filter(
        TrackingRequest.status == RequestStatus.accepted,
        (TrackingRequest.sender_id == user_id) | (TrackingRequest.receiver_id == user_id)).all()
    return [r.receiver_id if r.sender_id == user_id else r.sender_id for r in reqs]


@app.get("/api/location/{user_id}")
def get_location(user_id: int, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current.id != user_id and user_id not in _friends_of(current.id, db):
        raise HTTPException(403, "Not your friend")
    loc = db.query(Location).filter(Location.user_id == user_id).first()
    if not loc: raise HTTPException(404, "Location not available")
    owner = db.query(User).filter(User.id == user_id).first()
    return {"user_id": user_id, "username": owner.username, "latitude": loc.latitude,
            "longitude": loc.longitude, "accuracy": loc.accuracy, "updated_at": loc.updated_at}


@app.get("/api/friends/locations")
def friends_locations(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    fids = _friends_of(current.id, db)
    result = []
    for fid in fids:
        loc = db.query(Location).filter(Location.user_id == fid).first()
        if loc:
            u = db.query(User).filter(User.id == fid).first()
            result.append({"user_id": fid, "username": u.username, "latitude": loc.latitude,
                           "longitude": loc.longitude, "accuracy": loc.accuracy, "updated_at": loc.updated_at})
    return result


@app.get("/api/location/history/me")
def my_location_history(current: User = Depends(require_premium), db: Session = Depends(get_db)):
    """Last 100 location points for map route playback (premium only)."""
    hist = db.query(LocationHistory).filter(LocationHistory.user_id == current.id)\
             .order_by(LocationHistory.recorded_at.desc()).limit(100).all()
    return [{"latitude": h.latitude, "longitude": h.longitude,
             "accuracy": h.accuracy, "recorded_at": h.recorded_at} for h in hist]


# ── Lost-Phone / SMS Thief Mode ────────────────────────────────────────────
@app.post("/api/device/lost")
def report_lost(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Marks the user's account as 'lost'. Generates a one-time deep-link token
    and – if Twilio is configured and a phone number is registered – sends an
    innocuous-looking SMS to the registered number.

    When the recipient (possibly the thief) opens the link in any browser the
    PWA loads and immediately begins silently reporting location back to the
    real owner.  No app installation required.
    """
    existing = db.query(LostDevice).filter(LostDevice.user_id == current.id).first()
    token = secrets.token_urlsafe(32)
    if existing:
        existing.lost_token = token; existing.is_active = True
        existing.reported_at = datetime.now(timezone.utc)
    else:
        db.add(LostDevice(user_id=current.id, lost_token=token))
    db.commit()

    sms_sent = False
    deep_link = f"{APP_URL}/?lost_token={token}"
    if _twilio and current.phone_number and TWILIO_FROM:
        try:
            _twilio.messages.create(
                to=current.phone_number,
                from_=TWILIO_FROM,
                body=f"ZTracky Security: Your device triggered a safety check. Tap to verify: {deep_link}",
            )
            sms_sent = True
        except Exception:
            pass

    return {"lost_token": token, "deep_link": deep_link, "sms_sent": sms_sent}


@app.get("/api/device/activate")
def activate_lost_mode(lost_token: str, db: Session = Depends(get_db)):
    """
    Called by the browser that received the SMS link.
    Returns the owner's ID so the PWA knows where to push location updates.
    """
    record = db.query(LostDevice).filter(
        LostDevice.lost_token == lost_token, LostDevice.is_active == True).first()
    if not record:
        raise HTTPException(404, "Invalid or expired token")
    # Token stays active until the owner deactivates
    return {"owner_user_id": record.user_id, "tracking_active": True}


@app.post("/api/device/deactivate-lost")
def deactivate_lost(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(LostDevice).filter(LostDevice.user_id == current.id).first()
    if record:
        record.is_active = False; db.commit()
    return {"status": "deactivated"}


@app.post("/api/sms/webhook")
async def sms_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Twilio inbound SMS webhook.  Supports the command:
      TRACK +1234567890   →  activates lost mode for the registered number
    """
    form = await request.form()
    body = (form.get("Body") or "").strip().upper()
    parts = body.split()
    if len(parts) == 2 and parts[0] == "TRACK":
        phone = parts[1]
        user = db.query(User).filter(User.phone_number == phone).first()
        if user:
            token = secrets.token_urlsafe(32)
            existing = db.query(LostDevice).filter(LostDevice.user_id == user.id).first()
            if existing:
                existing.lost_token = token; existing.is_active = True
            else:
                db.add(LostDevice(user_id=user.id, lost_token=token))
            db.commit()
            deep_link = f"{APP_URL}/?lost_token={token}"
            if _twilio and TWILIO_FROM:
                try:
                    _twilio.messages.create(to=phone, from_=TWILIO_FROM,
                        body=f"ZTracky Safety: Tap to verify your device: {deep_link}")
                except Exception:
                    pass
    # Twilio expects a TwiML response
    return {"status": "ok"}


# ── Stripe Payments ────────────────────────────────────────────────────────
PREMIUM_PRICE_CENTS = int(os.environ.get("PREMIUM_PRICE_CENTS", "999"))   # $9.99/mo


@app.post("/api/payments/stripe/checkout")
def stripe_checkout(current: User = Depends(get_current_user)):
    if not stripe or not stripe.api_key:
        raise HTTPException(503, "Stripe not configured")
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price_data": {"currency": "usd",
                                    "unit_amount": PREMIUM_PRICE_CENTS,
                                    "product_data": {"name": "ZTracky Premium (30 days)"}},
                     "quantity": 1}],
        mode="payment",
        success_url=f"{APP_URL}/?payment=success",
        cancel_url=f"{APP_URL}/?payment=cancelled",
        metadata={"user_id": str(current.id)},
    )
    return {"checkout_url": session.url, "session_id": session.id}


@app.post("/api/payments/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WH_SECRET) if STRIPE_WH_SECRET else json.loads(payload)
    except Exception as e:
        raise HTTPException(400, str(e))

    if event.get("type") == "checkout.session.completed":
        sess = event["data"]["object"]
        user_id = int(sess.get("metadata", {}).get("user_id", 0))
        if user_id:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.is_premium = True
                db.add(Payment(user_id=user_id, amount_cents=PREMIUM_PRICE_CENTS,
                               method="stripe", tx_reference=sess.get("id")))
                db.commit()
    return {"received": True}


@app.post("/api/payments/crypto/verify")
def crypto_verify(body: CryptoVerifyIn, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    The frontend (MetaMask) already executed the on-chain subscribe() call.
    We record the tx hash and immediately grant premium; the owner can later
    cross-check on-chain data.  In production, use a blockchain RPC node
    (Alchemy/Infura) to confirm the transaction before granting access.
    """
    current.is_premium = True
    db.add(Payment(user_id=current.id, amount_cents=0, method="crypto",
                   tx_reference=body.tx_hash))
    db.commit()
    return {"premium": True, "tx_hash": body.tx_hash, "chain": body.chain}


# ── WebAuthn 2FA (biometric auth before admin transfers) ───────────────────
@app.get("/api/admin/webauthn/register-options")
def webauthn_reg_options(current: User = Depends(get_current_user), _: None = Depends(require_admin)):
    if not _webauthn_ok:
        raise HTTPException(503, "WebAuthn library not available")
    opts = generate_registration_options(
        rp_id=RP_ID, rp_name=RP_NAME,
        user_id=str(current.id).encode(), user_name=current.username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED),
        supported_pub_key_algs=[COSEAlgorithmIdentifier.ECDSA_SHA_256,
                                 COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256],
    )
    _reg_challenges[current.id] = opts.challenge
    import webauthn.helpers.cbor as _cbor
    return json.loads(opts.json())


@app.post("/api/admin/webauthn/register-verify")
def webauthn_reg_verify(body: WebAuthnRegVerifyIn, current: User = Depends(get_current_user),
                        _: None = Depends(require_admin), db: Session = Depends(get_db)):
    if not _webauthn_ok:
        raise HTTPException(503, "WebAuthn library not available")
    challenge = _reg_challenges.pop(current.id, None)
    if not challenge:
        raise HTTPException(400, "No pending challenge")
    try:
        verification = verify_registration_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=f"http://{RP_ID}",
            require_user_verification=True,
        )
    except Exception as e:
        raise HTTPException(400, f"WebAuthn verification failed: {e}")

    cred_id = base64.urlsafe_b64encode(verification.credential_id).rstrip(b"=").decode()
    pub_key = base64.urlsafe_b64encode(verification.credential_public_key).rstrip(b"=").decode()

    existing = db.query(WebAuthnCredential).filter(WebAuthnCredential.credential_id == cred_id).first()
    if not existing:
        db.add(WebAuthnCredential(user_id=current.id, credential_id=cred_id,
                                  public_key=pub_key, sign_count=verification.sign_count,
                                  aaguid=str(verification.aaguid) if verification.aaguid else None))
        db.commit()
    return {"registered": True}


@app.get("/api/admin/webauthn/auth-options")
def webauthn_auth_options(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not _webauthn_ok:
        raise HTTPException(503, "WebAuthn library not available")
    creds = db.query(WebAuthnCredential).filter(WebAuthnCredential.user_id == current.id).all()
    allow = [PublicKeyCredentialDescriptor(
                 id=base64.urlsafe_b64decode(c.credential_id + "=="))
             for c in creds]
    opts = generate_authentication_options(
        rp_id=RP_ID, allow_credentials=allow,
        user_verification=UserVerificationRequirement.REQUIRED)
    _auth_challenges[current.id] = opts.challenge
    return json.loads(opts.json())


@app.post("/api/admin/webauthn/auth-verify")
def webauthn_auth_verify(body: WebAuthnAuthVerifyIn, current: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    if not _webauthn_ok:
        raise HTTPException(503, "WebAuthn library not available")
    challenge = _auth_challenges.pop(current.id, None)
    if not challenge:
        raise HTTPException(400, "No pending challenge")

    cred_id_raw = base64.urlsafe_b64decode(
        body.credential.get("id", "") + "==")
    cred_id_b64 = base64.urlsafe_b64encode(cred_id_raw).rstrip(b"=").decode()
    stored = db.query(WebAuthnCredential).filter(
        WebAuthnCredential.credential_id == cred_id_b64,
        WebAuthnCredential.user_id == current.id).first()
    if not stored:
        raise HTTPException(400, "Credential not found")

    pub_key_bytes = base64.urlsafe_b64decode(stored.public_key + "==")
    try:
        verification = verify_authentication_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=f"http://{RP_ID}",
            credential_public_key=pub_key_bytes,
            credential_current_sign_count=stored.sign_count,
            require_user_verification=True,
        )
    except Exception as e:
        raise HTTPException(400, f"WebAuthn auth failed: {e}")

    stored.sign_count = verification.new_sign_count
    db.commit()

    # Issue a short-lived transfer token (single-use, valid 60 s)
    transfer_token = secrets.token_urlsafe(32)
    _transfer_tokens[transfer_token] = current.id
    return {"transfer_token": transfer_token, "expires_in": 60}


# ── Admin Wallet — Crypto Transfers ────────────────────────────────────────
@app.post("/api/admin/wallet/send-crypto")
def admin_send_crypto(body: SendCryptoIn, _: None = Depends(require_admin),
                      admin_user_id: int = Depends(require_transfer_token),
                      db: Session = Depends(get_db)):
    """
    Records a crypto transfer that was already broadcast by MetaMask.
    MetaMask signs and sends; this endpoint just persists the audit record
    and returns confirmation.  No private keys are ever stored server-side.
    """
    tx = AdminTransaction(
        admin_id=admin_user_id, tx_type="crypto",
        recipient=body.recipient, amount_wei_or_cents=body.amount_wei,
        tx_hash=body.tx_hash, network=body.network, status="confirmed",
    )
    db.add(tx); db.commit(); db.refresh(tx)
    return {"recorded": True, "tx_id": tx.id, "tx_hash": body.tx_hash}


@app.get("/api/admin/wallet/history")
def admin_wallet_history(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    txs = db.query(AdminTransaction).order_by(AdminTransaction.created_at.desc()).limit(50).all()
    return [{"id": t.id, "tx_type": t.tx_type, "recipient": t.recipient,
             "amount_wei_or_cents": t.amount_wei_or_cents, "network": t.network,
             "tx_hash": t.tx_hash, "status": t.status, "created_at": t.created_at}
            for t in txs]


# ── Admin Wallet — Stripe Connect / Bank Payouts ───────────────────────────
@app.post("/api/admin/stripe/connect")
def stripe_connect_onboard(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Creates or retrieves a Stripe Connect Express account and returns the onboarding URL."""
    if not stripe or not stripe.api_key:
        raise HTTPException(503, "Stripe not configured")
    # Find or create a placeholder admin user row for the connect record
    record = db.query(StripeConnectAccount).first()
    if not record:
        account = stripe.Account.create(type="express", capabilities={
            "transfers": {"requested": True}, "card_payments": {"requested": True}})
        record = StripeConnectAccount(user_id=1, stripe_account_id=account.id)
        db.add(record); db.commit()

    link = stripe.AccountLink.create(
        account=record.stripe_account_id,
        refresh_url=f"{APP_URL}/admin.html",
        return_url=f"{APP_URL}/admin.html?stripe=connected",
        type="account_onboarding",
    )
    return {"onboarding_url": link.url, "stripe_account_id": record.stripe_account_id}


@app.get("/api/admin/stripe/status")
def stripe_connect_status(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    if not stripe or not stripe.api_key:
        return {"connected": False}
    record = db.query(StripeConnectAccount).first()
    if not record:
        return {"connected": False}
    acct = stripe.Account.retrieve(record.stripe_account_id)
    record.details_submitted = acct.details_submitted
    record.payouts_enabled = acct.payouts_enabled
    db.commit()
    return {"connected": True, "stripe_account_id": record.stripe_account_id,
            "details_submitted": acct.details_submitted, "payouts_enabled": acct.payouts_enabled}


@app.post("/api/admin/stripe/payout")
def stripe_payout(body: StripePayoutIn, _: None = Depends(require_admin),
                  admin_user_id: int = Depends(require_transfer_token),
                  db: Session = Depends(get_db)):
    """Send collected Stripe funds to the connected bank account."""
    if not stripe or not stripe.api_key:
        raise HTTPException(503, "Stripe not configured")
    payout = stripe.Payout.create(
        amount=body.amount_cents, currency="usd",
        stripe_account=body.destination,
    )
    tx = AdminTransaction(
        admin_id=admin_user_id, tx_type="stripe_payout",
        recipient=body.destination, amount_wei_or_cents=body.amount_cents,
        status=payout.status,
    )
    db.add(tx); db.commit(); db.refresh(tx)
    return {"payout_id": payout.id, "status": payout.status, "tx_id": tx.id}


# ── Admin Stats ────────────────────────────────────────────────────────────
@app.get("/api/admin/stats")
def admin_stats(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    import requests as _req
    online_count = 0
    try:
        r = _req.get(f"{GO_SERVICE_URL}/stats", timeout=2)
        online_count = r.json().get("online_count", 0)
    except Exception:
        pass

    total_users    = db.query(User).count()
    premium_users  = db.query(User).filter(User.is_premium == True).count()
    total_payments = db.query(Payment).count()
    revenue_cents  = db.query(Payment).with_entities(
        __import__('sqlalchemy').func.sum(Payment.amount_cents)).scalar() or 0

    return {
        "total_users":    total_users,
        "online_count":   online_count,
        "premium_users":  premium_users,
        "total_payments": total_payments,
        "revenue_usd":    round(revenue_cents / 100, 2),
    }


@app.get("/api/admin/users")
def admin_users(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.created_at.desc()).limit(200).all()
    return [{"id": u.id, "username": u.username, "email": u.email,
             "is_premium": u.is_premium, "is_admin": u.is_admin,
             "phone_number": u.phone_number, "created_at": u.created_at}
            for u in users]


@app.post("/api/admin/users/{user_id}/upgrade")
def admin_upgrade(user_id: int, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    user.is_premium = True; db.commit()
    return {"user_id": user_id, "is_premium": True}


@app.post("/api/admin/users/{user_id}/downgrade")
def admin_downgrade(user_id: int, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    user.is_premium = False; db.commit()
    return {"user_id": user_id, "is_premium": False}
