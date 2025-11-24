# auth.py
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from pydantic import BaseModel
from app.config import settings

oauth = HTTPBearer()

class User(BaseModel):
    user_id: str
    team_id: str | None = None
    project_id: str | None = None
    company_id: str | None = None
    roles: list = []

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(oauth)) -> User:
    if creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")

    token = creds.credentials
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": True}
        )

        # OWNER = no scope needed ⚡
        if "owner" in payload.get("roles", []):
            return User(
                user_id=payload["user_id"],
                roles=["owner"]
            )

        # Others MUST have scope
        required_fields = ["user_id", "team_id", "project_id", "company_id"]
        for f in required_fields:
            if f not in payload:
                raise HTTPException(401, detail=f"Invalid token payload: missing {f}")

        return User(
            user_id=payload["user_id"],
            team_id=payload["team_id"],
            project_id=payload["project_id"],
            company_id=payload["company_id"],
            roles=payload.get("roles", []),
        )

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
