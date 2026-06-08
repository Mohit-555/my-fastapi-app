from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.database import get_db
from app.models.models import RefreshToken, User
from app.models.schemas import (
    UserRegisterRequest, UserLoginRequest,
    LogoutRequest, LogoutResponse, RefreshTokenRequest,
    TokenResponse, UserResponse
)
from app.auth_utils import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    hash_refresh_token,
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS, REMEMBER_ME_EXPIRE_DAYS
)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _issue_tokens(user: User, db: Session, remember_me: bool = False) -> TokenResponse:
    access_expire = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_expire = (
        timedelta(days=REMEMBER_ME_EXPIRE_DAYS)
        if remember_me
        else timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    refresh_token = create_refresh_token()
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(refresh_token),
        remember_me=remember_me,
        expires_at=datetime.utcnow() + refresh_expire,
    ))
    db.commit()

    return TokenResponse(
        access_token=create_access_token({"sub": user.employee_id}, access_expire),
        refresh_token=refresh_token,
        expires_in=int(access_expire.total_seconds()),
    )


@router.post("/register", response_model=UserResponse, status_code=201)
def register(payload: UserRegisterRequest, db: Session = Depends(get_db)):
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    if db.query(User).filter(User.employee_id == payload.employee_id).first():
        raise HTTPException(status_code=400, detail="Employee ID already registered")

    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
    full_name=payload.full_name,
    employee_id=payload.employee_id,
    designation=payload.designation,
    role_id=payload.role_id,
    zone_id=payload.zone_id,
    division_id=payload.division_id,
    mobile_number=payload.mobile_number,
    email=payload.email,
    hashed_password=hash_password(payload.password),
    reporting_officer_id=payload.reporting_officer_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.employee_id == payload.employee_id).first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid employee ID or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated. Contact admin.")

    return _issue_tokens(user, db, payload.remember_me)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    token_hash = hash_refresh_token(payload.refresh_token)
    refresh_token = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if (
        not refresh_token
        or refresh_token.revoked_at is not None
        or refresh_token.expires_at <= datetime.utcnow()
    ):
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = db.query(User).filter(User.id == refresh_token.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    refresh_token.revoked_at = datetime.utcnow()
    db.commit()
    return _issue_tokens(user, db, remember_me=refresh_token.remember_me)


@router.post("/logout", response_model=LogoutResponse)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)):
    token_hash = hash_refresh_token(payload.refresh_token)
    refresh_token = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if refresh_token and refresh_token.revoked_at is None:
        refresh_token.revoked_at = datetime.utcnow()
        db.commit()

    return LogoutResponse(message="Logged out successfully")


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user
