# login.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from jose import jwt
from sqlalchemy import text
import bcrypt   # <-- Only this is needed

from .config import settings
from .db import SessionLocal

router = APIRouter()

# ---------- MODELS ----------
class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    user_id: str           # human-friendly username (used in memberships.user_id)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    company_id: str
    team_id: str
    project_id: str


# ---------- HELPERS ----------
def hash_password(password: str) -> str:
    """Hash the password using bcrypt"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify bcrypt password"""
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ---------- ROUTES ----------
@router.post("/signup")
def signup(data: SignupRequest):
    """
    Create a REAL user with email + password.
    Does NOT give any role or project access.
    Admin will later attach memberships.
    """
    session = SessionLocal()

    # check if email or user_id already used
    existing = session.execute(
        text("""
            SELECT 1 FROM users
            WHERE email = :email OR user_id = :user_id
        """),
        {"email": data.email, "user_id": data.user_id}
    ).fetchone()

    if existing:
        session.close()
        raise HTTPException(status_code=400, detail="User with this email or user_id already exists")

    pwd_hash = hash_password(data.password)

    session.execute(
        text("""
            INSERT INTO users (id, user_id, email, password_hash)
            VALUES (gen_random_uuid(), :user_id, :email, :password_hash)
        """),
        {
            "user_id": data.user_id,
            "email": data.email,
            "password_hash": pwd_hash,
        }
    )

    session.commit()
    session.close()

    return {"status": "ok", "message": "User created. Ask an admin to give you access to a project."}


@router.post("/login")
def login(data: LoginRequest):
    """
    Real login:
    - Check email + password
    - Ensure user has membership for the given (company, team, project)
    - Put that role + project info inside JWT
    """
    session = SessionLocal()

    # 1) Find user by email
    row = session.execute(
        text("""
            SELECT user_id, email, password_hash
            FROM users
            WHERE email = :email
        """),
        {"email": data.email}
    ).mappings().fetchone()

    if not row:
        session.close()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(data.password, row["password_hash"]):
        session.close()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user_id = row["user_id"]

    # 2) Check that this user has membership for this project
    membership = session.execute(
        text("""
            SELECT role
            FROM memberships
            WHERE user_id   = :user_id
              AND company_id = :company_id
              AND team_id    = :team_id
              AND project_id = :project_id
        """),
        {
            "user_id": user_id,
            "company_id": data.company_id,
            "team_id": data.team_id,
            "project_id": data.project_id,
        }
    ).mappings().fetchone()

    if not membership:
        session.close()
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this project. Contact your manager/admin."
        )

    role = membership["role"]

    # 3) Build JWT
    payload = {
        "user_id": user_id,
        "company_id": data.company_id,
        "team_id": data.team_id,
        "project_id": data.project_id,
        "roles": [role],  # still a list, used everywhere else
        "exp": datetime.utcnow() + timedelta(hours=12),
    }

    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    session.close()

    return {"access_token": token, "token_type": "bearer"}
