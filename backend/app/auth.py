import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import LoginSession, User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
profile_router = APIRouter(prefix="/api/v1/users", tags=["users"])
hasher = PasswordHasher()
_dummy_hash = hasher.hash("invalid-password-placeholder")
@lru_cache
def get_engine():
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_db():
    with Session(get_engine()) as db:
        yield db


def limit_login(request: Request, db: Session = Depends(get_db)):
    from app.rate_limit import check_limit
    check_limit(request, db, "login", 10)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


class Register(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)


class Login(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class Profile(BaseModel):
    email: EmailStr
    display_name: str


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


def public_user(user: User):
    return {"id": user.id, "email": user.email, "display_name": user.display_name}


def current_session(token: str | None = Cookie(default=None, alias="zhiyan_session"), db: Session = Depends(get_db)):
    if not token or len(token) > 256:
        raise HTTPException(401, "请先登录")
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == digest(token)))
    if not session or session.revoked_at or session.expires_at <= now():
        raise HTTPException(401, "登录已过期，请重新登录")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "请先登录")
    return session, user


@router.post("/register", status_code=201)
def register(data: Register, db: Session = Depends(get_db)):
    name = data.display_name.strip()
    if not name:
        raise HTTPException(422, "请输入姓名")
    email = str(data.email)
    user = User(email=email, email_norm=email.casefold(), display_name=name, password_hash=hasher.hash(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if db.scalar(select(User.id).where(User.email_norm == email.casefold())):
            raise HTTPException(409, "该邮箱已注册") from None
        raise exc
    db.refresh(user)
    return public_user(user)


@router.post("/login", dependencies=[Depends(limit_login)])
def login(data: Login, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email_norm == str(data.email).casefold()))
    try:
        valid = hasher.verify(user.password_hash if user else _dummy_hash, data.password)
    except (VerifyMismatchError, InvalidHashError):
        valid = False
    if not user or not valid:
        raise HTTPException(401, "邮箱或密码错误")
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(user_id=user.id, token_hash=digest(token), expires_at=now() + timedelta(days=7)))
    db.commit()
    response.set_cookie("zhiyan_session", token, httponly=True, secure=get_settings().secure_cookies, samesite="lax", max_age=604800, path="/")
    return public_user(user)


@router.get("/me")
def me(current=Depends(current_session)):
    return public_user(current[1])


@profile_router.get("/me", response_model=Profile)
def get_profile(current=Depends(current_session)):
    user = current[1]
    return Profile(email=user.email, display_name=user.display_name)


@profile_router.patch("/me", response_model=Profile)
def update_profile(data: ProfileUpdate, current=Depends(current_session), db: Session = Depends(get_db)):
    user = current[1]
    user.display_name = data.display_name
    profile = Profile(email=user.email, display_name=user.display_name)
    db.commit()
    return profile


@router.post("/logout", status_code=204)
def logout(response: Response, current=Depends(current_session), db: Session = Depends(get_db)):
    current[0].revoked_at = now()
    db.commit()
    response.delete_cookie("zhiyan_session", path="/")
    response.status_code = 204
