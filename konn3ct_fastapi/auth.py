import os
import jwt
from datetime import datetime, timedelta
from fastapi import Request, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from database import get_db
from models import User

SECRET_KEY = os.environ.get("DASHBOARD_SECRET_KEY", "konn3ct-super-secret-key-12345")
ALGORITHM = "HS256"

# API Key security scheme for Swagger UI & automated integrations
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_current_user(
    request: Request,
    api_key: str = Depends(api_key_header),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency that retrieves the current authenticated user.
    Checks X-API-Key header first, then Authorization Bearer token, then 'token' cookie.
    """
    # 1. API Key Auth
    if api_key:
        user = db.query(User).filter(User.api_key == api_key).first()
        if user:
            return user

    # 2. Extract Token
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        
    if not token:
        # Fallback to cookie
        token = request.cookies.get("token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials missing"
        )

    # 3. Decode & Validate JWT Token
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload"
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
        
    return user

class RoleChecker:
    """Dependency checker to enforce roles."""
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: User = Depends(get_current_user)):
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: Insufficient permissions"
            )
        return current_user
