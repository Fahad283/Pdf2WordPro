import hashlib
import time
from threading import Lock

from fastapi import HTTPException, Request
from redis import Redis, RedisError

from app.core.config import get_settings

settings = get_settings()
redis_client = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
local_limits: dict[str, int] = {}
local_window = 0
local_lock = Lock()


def throttle(request: Request, scope: str, limit: int, owner_key: str | None = None) -> None:
    global local_window
    address = owner_key or (request.client.host if request.client else "unknown")
    digest = hashlib.sha256(address.encode()).hexdigest()[:32]
    window = int(time.time()) // 60
    key = f"pdfpro:rate:{scope}:{window}:{digest}"
    if settings.celery_task_always_eager:
        with local_lock:
            if local_window != window:
                local_limits.clear()
                local_window = window
            count = local_limits.get(key, 0) + 1
            local_limits[key] = count
    else:
        try:
            with redis_client.pipeline() as pipeline:
                pipeline.incr(key)
                pipeline.expire(key, 90, nx=True)
                count, _ = pipeline.execute()
        except RedisError:
            raise HTTPException(503, "Job coordination is temporarily unavailable.") from None
    if count > limit:
        raise HTTPException(429, "Too many requests. Try again shortly.", headers={"Retry-After": "60"})
