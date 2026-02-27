from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime, timezone

from database import get_db, create_tables, User, TrackingRequest, Location, RequestStatus
from auth import hash_password, verify_password, create_access_token, decode_token

app = FastAPI(title="ZTracky API", description="Location tracking with friend requests", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    # allow_origins=["*"] is suitable for self-hosted / local deployments.
    # In production, replace with your specific domain(s):
    #   allow_origins=["https://yourdomain.com"]
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")


@app.on_event("startup")
def startup():
    create_tables()


# --- Schemas ---

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserOut


class RequestOut(BaseModel):
    id: int
    sender_id: int
    receiver_id: int
    sender_username: str
    receiver_username: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class LocationUpdate(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None


class LocationOut(BaseModel):
    user_id: int
    username: str
    latitude: float
    longitude: float
    accuracy: Optional[float]
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Auth helpers ---

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == int(payload.get("sub", 0))).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


# --- Routes ---

@app.post("/api/register", response_model=Token, status_code=201)
def register(data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(or_(User.username == data.username, User.email == data.email)).first():
        raise HTTPException(status_code=400, detail="Username or email already registered")
    user = User(username=data.username, email=data.email, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.post("/api/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.get("/api/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@app.post("/api/requests/send", response_model=RequestOut, status_code=201)
def send_request(username: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if username == current_user.username:
        raise HTTPException(status_code=400, detail="Cannot send request to yourself")
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    existing = db.query(TrackingRequest).filter(
        or_(
            and_(TrackingRequest.sender_id == current_user.id, TrackingRequest.receiver_id == target.id),
            and_(TrackingRequest.sender_id == target.id, TrackingRequest.receiver_id == current_user.id),
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="A request already exists between these users")
    req = TrackingRequest(sender_id=current_user.id, receiver_id=target.id)
    db.add(req)
    db.commit()
    db.refresh(req)
    return _request_out(req, db)


@app.get("/api/requests", response_model=List[RequestOut])
def list_requests(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reqs = db.query(TrackingRequest).filter(
        or_(TrackingRequest.sender_id == current_user.id, TrackingRequest.receiver_id == current_user.id)
    ).all()
    return [_request_out(r, db) for r in reqs]


@app.post("/api/requests/{request_id}/accept", response_model=RequestOut)
def accept_request(request_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    req = db.query(TrackingRequest).filter(
        TrackingRequest.id == request_id,
        TrackingRequest.receiver_id == current_user.id,
        TrackingRequest.status == RequestStatus.pending,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Pending request not found")
    req.status = RequestStatus.accepted
    req.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(req)
    return _request_out(req, db)


@app.post("/api/requests/{request_id}/reject", response_model=RequestOut)
def reject_request(request_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    req = db.query(TrackingRequest).filter(
        TrackingRequest.id == request_id,
        TrackingRequest.receiver_id == current_user.id,
        TrackingRequest.status == RequestStatus.pending,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Pending request not found")
    req.status = RequestStatus.rejected
    req.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(req)
    return _request_out(req, db)


@app.get("/api/friends", response_model=List[UserOut])
def list_friends(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    accepted = db.query(TrackingRequest).filter(
        or_(TrackingRequest.sender_id == current_user.id, TrackingRequest.receiver_id == current_user.id),
        TrackingRequest.status == RequestStatus.accepted,
    ).all()
    friend_ids = {r.sender_id if r.receiver_id == current_user.id else r.receiver_id for r in accepted}
    return db.query(User).filter(User.id.in_(friend_ids)).all()


@app.post("/api/location", response_model=LocationOut)
def update_location(data: LocationUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    loc = db.query(Location).filter(Location.user_id == current_user.id).first()
    if loc:
        loc.latitude = data.latitude
        loc.longitude = data.longitude
        loc.accuracy = data.accuracy
        loc.updated_at = datetime.now(timezone.utc)
    else:
        loc = Location(user_id=current_user.id, latitude=data.latitude, longitude=data.longitude, accuracy=data.accuracy)
        db.add(loc)
    db.commit()
    db.refresh(loc)
    return LocationOut(
        user_id=loc.user_id,
        username=current_user.username,
        latitude=loc.latitude,
        longitude=loc.longitude,
        accuracy=loc.accuracy,
        updated_at=loc.updated_at,
    )


@app.get("/api/location/{user_id}", response_model=LocationOut)
def get_location(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Must be accepted friends to view location
    friendship = db.query(TrackingRequest).filter(
        or_(
            and_(TrackingRequest.sender_id == current_user.id, TrackingRequest.receiver_id == user_id),
            and_(TrackingRequest.sender_id == user_id, TrackingRequest.receiver_id == current_user.id),
        ),
        TrackingRequest.status == RequestStatus.accepted,
    ).first()
    if not friendship and user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this user's location")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    loc = db.query(Location).filter(Location.user_id == user_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not available for this user")
    return LocationOut(
        user_id=loc.user_id,
        username=target.username,
        latitude=loc.latitude,
        longitude=loc.longitude,
        accuracy=loc.accuracy,
        updated_at=loc.updated_at,
    )


@app.get("/api/friends/locations", response_model=List[LocationOut])
def get_friends_locations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    accepted = db.query(TrackingRequest).filter(
        or_(TrackingRequest.sender_id == current_user.id, TrackingRequest.receiver_id == current_user.id),
        TrackingRequest.status == RequestStatus.accepted,
    ).all()
    friend_ids = {r.sender_id if r.receiver_id == current_user.id else r.receiver_id for r in accepted}
    result = []
    for fid in friend_ids:
        loc = db.query(Location).filter(Location.user_id == fid).first()
        if loc:
            friend = db.query(User).filter(User.id == fid).first()
            result.append(LocationOut(
                user_id=loc.user_id,
                username=friend.username,
                latitude=loc.latitude,
                longitude=loc.longitude,
                accuracy=loc.accuracy,
                updated_at=loc.updated_at,
            ))
    return result


@app.get("/api/verify-token")
def verify_token(current_user: User = Depends(get_current_user)):
    return {"valid": True, "user_id": current_user.id, "username": current_user.username}


# --- Helpers ---

def _request_out(req: TrackingRequest, db: Session) -> RequestOut:
    sender = db.query(User).filter(User.id == req.sender_id).first()
    receiver = db.query(User).filter(User.id == req.receiver_id).first()
    return RequestOut(
        id=req.id,
        sender_id=req.sender_id,
        receiver_id=req.receiver_id,
        sender_username=sender.username if sender else "",
        receiver_username=receiver.username if receiver else "",
        status=req.status,
        created_at=req.created_at,
    )
