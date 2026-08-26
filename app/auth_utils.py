from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional
import hashlib
import secrets
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db, settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 1
REMEMBER_ME_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_scheme = HTTPBearer(auto_error=False)


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


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: Session = Depends(get_db),
):
    # EventSource can't set headers — allow ?token= as a fallback (same
    # contract the websocket endpoints use via extract_ws_token).
    token: str | None = credentials.credentials if credentials else request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=403, detail="Not authenticated")
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

def get_current_user_from_token(token: str, db: Session):
    """Validate a raw token string — used for SSE where headers aren't available."""
    user = get_user_from_token_optional(token, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def get_user_from_token_optional(token: str, db: Session):
    """Non-raising validation used by WebSocket handshakes. Returns the User
    or None instead of raising HTTPException (meaningless over WS)."""
    from app.models.models import User
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        employee_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        if not employee_id or token_type != "access":
            return None
    except JWTError:
        return None

    user = db.query(User).filter(User.employee_id == employee_id).first()
    if not user or not user.is_active:
        return None
    return user


def extract_ws_token(websocket) -> Optional[str]:
    """Pull a bearer token from a WebSocket handshake.

    Browsers cannot set headers on WebSocket connections, so clients pass
    `?token=<access_token>`; the Sec-WebSocket-Protocol trick and the plain
    Authorization header are also accepted for non-browser clients.
    """
    token = websocket.query_params.get("token")
    if token:
        return token
    # Sec-WebSocket-Protocol: "bearer, <token>"
    proto = websocket.headers.get("sec-websocket-protocol", "")
    if "," in proto:
        parts = [p.strip() for p in proto.split(",")]
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


# ── RBAC enforcement ─────────────────────────────────────────────────────
# Role.level semantics (rbac_defaults.DEFAULT_ROLES): lower number = more
# privilege. 1=HQ_ADMIN, 2=HQ_MONITOR, 3=DIVISION_ADMIN, 4=DIVISION_ENGINEER,
# 5=STATION_MASTER, 6=MAINTENANCE_ENGINEER, 7=GUEST, 8=AUDITOR.
ADMIN_MAX_LEVEL = 3

def _role_level(user) -> int:
    """Resolve a user's privilege level. Users without a resolvable role are
    treated as the LEAST privileged (level 99), never as admins."""
    role = getattr(user, "role", None)
    level = getattr(role, "level", None)
    return level if isinstance(level, int) else 99


def require_admin(current_user=Depends(get_current_user)):
    """Dependency: allow only administrative roles (level <= ADMIN_MAX_LEVEL).
    Any authenticated user passes plain get_current_user; this adds the role
    gate for management endpoints."""
    if _role_level(current_user) > ADMIN_MAX_LEVEL:
        raise HTTPException(
            status_code=403,
            detail="Insufficient role privileges for this operation"
        )
    return current_user


def require_min_level(max_level: int):
    """Dependency factory: allow roles with level <= max_level."""
    def dep(current_user=Depends(get_current_user)):
        if _role_level(current_user) > max_level:
            raise HTTPException(
                status_code=403,
                detail="Insufficient role privileges for this operation"
            )
        return current_user
    return dep
