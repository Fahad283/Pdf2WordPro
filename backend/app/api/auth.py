import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.core.rate_limit import throttle
from app.core.security import (
    check_password, clear_session, guest_owner, hasher, read_user, require_user, set_session,
)
from app.models import Batch, FileRecord, Job, User
from app.schemas import Credentials, UserView

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def bootstrap_admin() -> None:
    settings = get_settings()
    if not settings.admin_email:
        return
    credentials = Credentials(email=settings.admin_email, password=settings.admin_password)
    if len(credentials.password) < 12:
        raise RuntimeError("ADMIN_PASSWORD must contain at least 12 characters.")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == credentials.email))
        if user is None:
            db.add(User(email=credentials.email, password_hash=hasher.hash(credentials.password), role="admin"))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
        elif user.role != "admin":
            logger.warning("admin_email_already_registered")


def _claim_guest_uploads(request: Request, user: User, db: Session) -> None:
    owner = guest_owner(request)
    if owner:
        # Use one transaction so jobs, uploads and batches always follow the account together.
        for record in (FileRecord, Job, Batch):
            db.execute(update(record).where(record.owner_key == owner).values(
                owner_key=f"u:{user.id}", user_id=user.id,
            ))


@router.post("/register", response_model=UserView, status_code=201)
def register(
    payload: Credentials, request: Request, response: Response, db: Session = Depends(get_db),
) -> User:
    throttle(request, "register", 20)
    if len(payload.password) < 12:
        raise HTTPException(422, "Use a password with at least 12 characters.")
    user = User(email=payload.email, password_hash=hasher.hash(payload.password))
    db.add(user)
    try:
        db.flush()
        _claim_guest_uploads(request, user, db)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account already uses that email address.") from None
    set_session(response, user)
    return user


@router.post("/login", response_model=UserView)
def login(
    payload: Credentials, request: Request, response: Response, db: Session = Depends(get_db),
) -> User:
    throttle(request, "login-ip", 30)
    throttle(request, "login-account", 12, payload.email)
    user = db.scalar(select(User).where(User.email == payload.email))
    if not check_password(payload.password, user.password_hash if user else None) or user.status != "active":
        raise HTTPException(401, "The email address or password is incorrect.")
    _claim_guest_uploads(request, user, db)
    db.commit()
    set_session(response, user)
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    user = read_user(request, db)
    if user:
        db.execute(update(User).where(User.id == user.id).values(session_version=User.session_version + 1))
        db.commit()
    clear_session(response)


@router.get("/me", response_model=UserView)
def me(user: User = Depends(require_user)) -> User:
    return user
