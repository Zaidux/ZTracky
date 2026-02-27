from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Enum, ForeignKey, Boolean, Text, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timezone
import enum
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./ztracky.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class RequestStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    phone_number = Column(String, nullable=True)
    is_premium = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    stripe_customer_id = Column(String, nullable=True)
    linked_whatsapp = Column(String, nullable=True)   # WhatsApp phone number e.g. +1234567890
    linked_facebook = Column(String, nullable=True)   # Facebook username or profile URL
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    sent_requests = relationship("TrackingRequest", foreign_keys="TrackingRequest.sender_id", back_populates="sender")
    received_requests = relationship("TrackingRequest", foreign_keys="TrackingRequest.receiver_id", back_populates="receiver")
    location = relationship("Location", back_populates="user", uselist=False)
    location_history = relationship("LocationHistory", back_populates="user")
    payments = relationship("Payment", back_populates="user")
    webauthn_credentials = relationship("WebAuthnCredential", back_populates="user")


class TrackingRequest(Base):
    __tablename__ = "tracking_requests"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    receiver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(Enum(RequestStatus), default=RequestStatus.pending, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    sender = relationship("User", foreign_keys=[sender_id], back_populates="sent_requests")
    receiver = relationship("User", foreign_keys=[receiver_id], back_populates="received_requests")


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="location")


class LocationHistory(Base):
    """Stores up to 100 recent location points per user (premium feature)."""
    __tablename__ = "location_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=True)
    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="location_history")


class Payment(Base):
    """Audit trail for Stripe and crypto payments."""
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount_cents = Column(Integer, nullable=False)          # USD cents
    method = Column(String, nullable=False)                 # "stripe" | "crypto"
    tx_reference = Column(String, nullable=True)            # Stripe session ID or chain tx hash
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="payments")


class LostDevice(Base):
    """Tracks phones reported as stolen. Generates one-time SMS deep-link tokens."""
    __tablename__ = "lost_devices"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    lost_token = Column(String, unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    reported_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WebAuthnCredential(Base):
    """FIDO2/WebAuthn credential for biometric 2FA (admin wallet transfers)."""
    __tablename__ = "webauthn_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    credential_id = Column(String, unique=True, nullable=False)   # base64url
    public_key = Column(Text, nullable=False)                     # base64url COSE key
    sign_count = Column(BigInteger, default=0)
    aaguid = Column(String, nullable=True)
    registered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="webauthn_credentials")


class StripeConnectAccount(Base):
    """Stripe Connect Express account for admin bank payouts."""
    __tablename__ = "stripe_connect_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    stripe_account_id = Column(String, nullable=False)
    details_submitted = Column(Boolean, default=False)
    payouts_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AdminTransaction(Base):
    """Audit log for admin-initiated crypto/bank transfers."""
    __tablename__ = "admin_transactions"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tx_type = Column(String, nullable=False)          # "crypto" | "stripe_payout"
    recipient = Column(String, nullable=False)        # wallet address or Stripe account
    amount_wei_or_cents = Column(BigInteger, nullable=False)
    tx_hash = Column(String, nullable=True)           # blockchain tx hash (crypto only)
    network = Column(String, nullable=True)           # "ethereum" | "polygon" etc.
    status = Column(String, default="pending")        # "pending" | "confirmed" | "failed"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Geofence(Base):
    """A geographic fence (circle) that triggers alerts on enter/exit."""
    __tablename__ = "geofences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    label = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    radius_meters = Column(Float, nullable=False, default=200.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class GeofenceAlert(Base):
    """Records when a user entered or exited a geofence."""
    __tablename__ = "geofence_alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    geofence_id = Column(Integer, ForeignKey("geofences.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)       # "enter" | "exit"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ChatMessage(Base):
    """Persisted in-app chat messages between friends."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    receiver_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    sender = relationship("User", foreign_keys=[sender_id])
    receiver = relationship("User", foreign_keys=[receiver_id])


class CallTrackingEvent(Base):
    """Records a call-based location tracking attempt (premium feature)."""
    __tablename__ = "call_tracking_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    caller_phone = Column(String, nullable=False)       # Phone number submitted for tracking
    carrier_name = Column(String, nullable=True)        # Carrier from Twilio Lookup
    carrier_country = Column(String, nullable=True)     # ISO country code
    line_type = Column(String, nullable=True)           # "mobile" | "landline" | "voip"
    # Estimated zone (anchored to the reporting user's location when available)
    estimated_latitude = Column(Float, nullable=True)
    estimated_longitude = Column(Float, nullable=True)
    confidence_radius_km = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)                 # Human-readable summary
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BugReportType(str, enum.Enum):
    bug = "bug"
    feature = "feature"


class BugReportStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"


class BugReport(Base):
    """User-submitted bug reports and feature requests."""
    __tablename__ = "bug_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    report_type = Column(Enum(BugReportType), default=BugReportType.bug, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    status = Column(Enum(BugReportStatus), default=BugReportStatus.open, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", foreign_keys=[user_id])
    replies = relationship("BugReportReply", back_populates="report", order_by="BugReportReply.created_at")


class BugReportReply(Base):
    """Replies on bug reports (chat-style conversation between user and admin)."""
    __tablename__ = "bug_report_replies"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("bug_reports.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # Who sent this reply
    is_admin_reply = Column(Boolean, default=False)  # True if admin replied
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    report = relationship("BugReport", back_populates="replies")
    user = relationship("User", foreign_keys=[user_id])


class ApiKey(Base):
    """User-generated API keys for CLI / third-party access.
    Created after WebAuthn (fingerprint) verification.
    Each key carries a set of permission scopes."""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    key_hash = Column(String, nullable=False, unique=True)    # SHA-256 of the raw key
    key_prefix = Column(String, nullable=False)               # First 8 chars for display
    label = Column(String, nullable=False, default="CLI")     # Human-readable name
    # Permissions stored as comma-separated scopes
    scopes = Column(String, nullable=False, default="read")   # e.g. "read,write,location,chat,friends"
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", foreign_keys=[user_id])


# All available API key scopes
API_KEY_SCOPES = [
    "read",       # Read own profile, friends list, locations
    "write",      # Update profile, settings
    "location",   # Send/receive location updates
    "friends",    # Send/accept/reject friend requests
    "chat",       # Send/read chat messages
    "tracking",   # Real-time tracking
    "reports",    # Submit bug reports
]


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    Base.metadata.create_all(bind=engine)
