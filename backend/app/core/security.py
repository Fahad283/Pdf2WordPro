import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.models import User

settings = get_settings()
GUEST_COOKIE = "pdfpro_guest"
AUTH_COOKIE = "pdfpro_session"
SESSION_AGE = 7 * 24 * 60 * 60
hasher = PasswordHasher(time_cost=2, memory_cost=32768, parallelism=2)
dummy_password_hash = hasher.hash(secrets.token_urlsafe(32))


@dataclass(frozen=True)
class Identity:
    owner_key: str
    user_id: str | None = None


def _sign(purpose: str, value: str) -> str:
    message = f"{purpose}.{value}".encode()
    signature = hmac.new(settings.secret_key.encode(), message, hashlib.sha256).hexdigest()
    return f"{value}.{signature}"


def _verify(purpose: str, token: str | None) -> str | None:
    if token and len(token) <= 220 and "." in token:
        value = token.rsplit(".", 1)[0]
        if hmac.compare_digest(_sign(purpose, value).encode(), token.encode()):
            return value
    return None


def _read_token(request: Request, cookie: str) -> list[str] | None:
    value = _verify(cookie, request.cookies.get(cookie))
    if value is None:
        return None
    fields = value.split(".")
    if not fields[-1].isdigit() or int(fields[-1]) <= time.time():
        return None
    return fields[:-1]


def _set_cookie(response: Response, cookie: str, value: str) -> None:
    value = f"{value}.{int(time.time()) + SESSION_AGE}"
    response.set_cookie(
        cookie,
        _sign(cookie, value),
        max_age=SESSION_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def guest_owner(request: Request) -> str | None:
    fields = _read_token(request, GUEST_COOKIE)
    return f"g:{fields[0]}" if fields and len(fields) == 1 else None


def read_user(request: Request, db: Session) -> User | None:
    fields = _read_token(request, AUTH_COOKIE)
    if not fields or len(fields) != 2 or not fields[1].isdigit():
        return None
    user = db.get(User, fields[0])
    if user and user.status == "active" and user.session_version == int(fields[1]):
        return user
    return None


def get_identity(request: Request, response: Response) -> Identity:
    with SessionLocal() as db:
        user = read_user(request, db)
    if user:
        return Identity(f"u:{user.id}", user.id)
    owner = guest_owner(request)
    if owner is None:
        token = secrets.token_urlsafe(24)
        owner = f"g:{token}"
        _set_cookie(response, GUEST_COOKIE, token)
    return Identity(owner)


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = read_user(request, db)
    if user is None:
        raise HTTPException(401, "Sign in to access your account.")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return user


def set_session(response: Response, user: User) -> None:
    _set_cookie(response, AUTH_COOKIE, f"{user.id}.{user.session_version}")
    response.delete_cookie(GUEST_COOKIE, httponly=True, secure=settings.cookie_secure, samesite="lax")


def clear_session(response: Response) -> None:
    for cookie in (AUTH_COOKIE, GUEST_COOKIE):
        response.delete_cookie(cookie, httponly=True, secure=settings.cookie_secure, samesite="lax")


def check_password(password: str, password_hash: str | None) -> bool:
    try:
        return hasher.verify(password_hash or dummy_password_hash, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False
