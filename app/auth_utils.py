from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
import hashlib
import secrets
from fastapi import HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database import get_db

SECRET_KEY = "change-this-to-a-long-random-secret"  # move to .env later
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 1
REMEMBER_ME_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: timedelta) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + expires_delta
    payload["type"] = "access"
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    from app.models.models import User
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        employee_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        if not employee_id or token_type != "access":
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(User).filter(User.employee_id == employee_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user
