import base64
import hashlib
import hmac

from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.core.rate_limit import redis_client

settings = get_settings()
secret_key = hmac.new(settings.secret_key.encode(), b"pdfpro:job-password", hashlib.sha256).digest()
cipher = Fernet(base64.urlsafe_b64encode(secret_key))


def _key(attempt: str) -> str:
    return f"pdfpro:job-secret:{attempt}"


def remember_password(attempt: str, password: str, ttl: int) -> None:
    redis_client.set(_key(attempt), cipher.encrypt(password.encode()), ex=max(1, ttl))


def take_password(attempt: str) -> str | None:
    encrypted = redis_client.getdel(_key(attempt))
    return cipher.decrypt(encrypted).decode() if encrypted else None


def has_password(attempt: str) -> bool:
    return bool(redis_client.exists(_key(attempt)))


def forget_password(attempt: str) -> None:
    if not settings.celery_task_always_eager:
        redis_client.delete(_key(attempt))
