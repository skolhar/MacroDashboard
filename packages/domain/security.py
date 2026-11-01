import hmac
import hashlib
import ipaddress
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from fastapi import Header, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from .models import OperatorCredential
from .settings import settings, token_digest


def require_admin(x_admin_token: str | None = Header(default=None)):
    digest = settings().admin_token_hash
    if not digest or not x_admin_token or not hmac.compare_digest(token_digest(x_admin_token), digest):
        raise HTTPException(status_code=401, detail="Administrative authentication required")
    return {"role": "admin"}


def authorize_token(session: Session, token: str | None, scope: str, legacy=False):
    if not token:
        raise HTTPException(401, "Administrative authentication required")
    digest = token_digest(token)
    cfg = settings()
    if legacy and cfg.environment in {"demo", "development"} and cfg.admin_token_hash and hmac.compare_digest(digest, cfg.admin_token_hash):
        return {"operator_id": "legacy-development", "scopes": ["imports:write", "ingestion:run"]}
    credential = session.get(OperatorCredential, digest)
    now = datetime.now(timezone.utc)
    if not credential or credential.revoked_at or credential.expires_at <= now:
        raise HTTPException(401, "Administrative authentication required")
    if scope not in credential.scopes.split(","):
        raise HTTPException(403, "Administrative scope required")
    return {"operator_id": credential.operator_id, "scopes": credential.scopes.split(",")}


def require_scope(scope: str):
    def dependency(request: Request, x_admin_token: str | None = Header(default=None)):
        from apps.api import main as api
        with Session(api.DB) as session:
            return authorize_token(session, x_admin_token, scope, legacy=True)
    return dependency


def client_identity(peer: str, asserted_ip: str | None, trusted_cidrs: tuple[str, ...]) -> str:
    """Only accept Caddy's overwritten client-IP header from an approved peer."""
    try:
        address = ipaddress.ip_address(peer)
        if asserted_ip and any(address in ipaddress.ip_network(cidr, strict=False) for cidr in trusted_cidrs):
            return str(ipaddress.ip_address(asserted_ip))
    except ValueError:
        pass
    return peer


class DatabaseRateLimiter:
    """Atomic PostgreSQL/SQLite upsert shared by all API workers."""
    def __init__(self, db):
        self.db = db

    def allow(self, key: str, limit: int, window_seconds: int = 60, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else now
        window = current // window_seconds * window_seconds
        digest = hashlib.sha256(key.encode()).hexdigest()
        try:
            with self.db.begin() as connection:
                row = connection.execute(text("""INSERT INTO rate_limit_counters (key, window_start, count)
                    VALUES (:key, :window, 1)
                    ON CONFLICT (key, window_start) DO UPDATE SET count = rate_limit_counters.count + 1
                    WHERE rate_limit_counters.count < :limit RETURNING count"""), {"key": digest, "window": window, "limit": limit}).first()
                return row is not None
        except SQLAlchemyError as exc:
            raise RateLimitStoreUnavailable("Shared rate-limit store unavailable") from exc

    def prune(self, now: int | None = None, retention_seconds: int = 3600) -> int:
        cutoff = (int(time.time()) if now is None else now) - retention_seconds
        try:
            with self.db.begin() as connection:
                return connection.execute(text("DELETE FROM rate_limit_counters WHERE window_start < :cutoff"), {"cutoff": cutoff}).rowcount
        except SQLAlchemyError as exc:
            raise RateLimitStoreUnavailable("Shared rate-limit store unavailable") from exc


class RateLimitStoreUnavailable(RuntimeError):
    pass


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
