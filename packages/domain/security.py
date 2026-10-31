import hmac
import threading
import time
from collections import defaultdict, deque
from fastapi import Header, HTTPException
from .settings import settings, token_digest


def require_admin(x_admin_token: str | None = Header(default=None)):
    digest = settings().admin_token_hash
    if not digest or not x_admin_token or not hmac.compare_digest(token_digest(x_admin_token), digest):
        raise HTTPException(status_code=401, detail="Administrative authentication required")
    return {"role": "admin"}


class RateLimiter:
    def __init__(self):
        self.events = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        with self.lock:
            bucket = self.events[key]
            while bucket and bucket[0] <= now - window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True
