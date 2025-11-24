# login.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from jose import jwt
import bcrypt

from app.config import settings
from .db import get_db

router = APIRouter()
db = get_db()

# ---------- MODELS ----------
class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    user_id: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    company_id: str | None = None
    team_id: str | None = None
    project_id: str | None = None



# ---------- HELPERS ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ---------- ROUTES ----------
@router.post("/signup")
def signup(data: SignupRequest):
    existing = db.users.find_one({
        "$or": [{"email": data.email}, {"user_id": data.user_id}]
    })

    if existing:
        raise HTTPException(400, "User with this email or user_id already exists")

    # 👉 Check if OWNER already exists
    owner_exists = db.users.find_one({"role": "owner"})
    is_owner = False

    if not owner_exists:
        is_owner = True  # first ever user becomes OWNER

    # Create user
    db.users.insert_one({
        "user_id": data.user_id,
        "email": data.email,
        "password_hash": hash_password(data.password),
        "role": "owner" if is_owner else "user",
    })

    # 🔥 ADD THIS → create membership for OWNER
    if is_owner:
        db.memberships.insert_one({
            "user_id": data.user_id,
            "company_id": "global",
            "team_id": "global",
            "project_id": "global",
            "role": "owner"
        })
        return {"status": "ok", "message": "OWNER created successfully. You control everything."}

    return {"status": "ok", "message": "Signup successful. Ask admin for access."}

# ---------- ROUTES ----------
@router.post("/login")
def login(data: LoginRequest):
    user = db.users.find_one({"email": data.email})

    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    # ---------------------------------------------
    # 1) OWNER LOGIN (no scope required)
    # ---------------------------------------------
    owner_membership = db.memberships.find_one({
        "user_id": user["user_id"],
        "role": "owner"     # 👈 check only role
    })

    if owner_membership:
        token = jwt.encode(
            {
                "user_id": user["user_id"],
                "roles": ["owner"],
                "exp": datetime.utcnow() + timedelta(hours=12)
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        return {
            "access_token": token,
            "token_type": "bearer",
            "message": "OWNER login successful"
        }

    # ---------------------------------------------
    # 2) NORMAL USER (must provide scope)
    # ---------------------------------------------
    membership = db.memberships.find_one({
        "user_id": user["user_id"],
        "company_id": data.company_id,
        "team_id": data.team_id,
        "project_id": data.project_id
    })

    if not membership:
        raise HTTPException(403, "You do not have access to this area")

    payload = {
        "user_id": user["user_id"],
        "company_id": data.company_id,
        "team_id": data.team_id,
        "project_id": data.project_id,
        "roles": [membership["role"]],
        "exp": datetime.utcnow() + timedelta(hours=12),
    }

    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    return {
        "access_token": token,
        "token_type": "bearer"
    }
