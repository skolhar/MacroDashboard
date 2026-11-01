"""Fail-closed runtime configuration. No secret is serialized into API responses."""
import hashlib
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    environment: str
    demo_mode: bool
    admin_token_hash: str | None
    database_url: str
    operator_auth_mode: str
    trusted_proxy_cidrs: tuple[str, ...]
    market_research_enabled: bool
    market_provider: str


def settings() -> Settings:
    environment = os.getenv("APP_ENV", "demo").lower()
    if environment not in {"development", "demo", "staging", "production"}:
        raise ValueError("APP_ENV must be development, demo, staging or production")
    raw_demo = os.getenv("DEMO_MODE")
    demo = environment == "demo" if raw_demo is None else raw_demo.lower() == "true"
    if environment in {"staging", "production"} and demo:
        raise ValueError("Demo observations are forbidden in staging and production")
    database_url = os.getenv("DATABASE_URL", "sqlite:///./macro.db" if environment in {"demo", "development"} else "")
    if not database_url:
        raise ValueError("DATABASE_URL is required outside development/demo")
    token_hash = os.getenv("ADMIN_TOKEN_SHA256") or None
    auth_mode = os.getenv("OPERATOR_AUTH_MODE", "legacy")
    if auth_mode not in {"legacy", "db"}:
        raise ValueError("Invalid OPERATOR_AUTH_MODE")
    if environment in {"staging", "production"}:
        if auth_mode != "db":
            raise ValueError("OPERATOR_AUTH_MODE=db is required in staging/production")
    if token_hash and (len(token_hash) != 64 or any(c not in "0123456789abcdef" for c in token_hash.lower())):
        raise ValueError("ADMIN_TOKEN_SHA256 must be a SHA-256 hex digest")
    cidrs = tuple(part.strip() for part in os.getenv("TRUSTED_PROXY_CIDRS", "").split(",") if part.strip())
    market_research = os.getenv("MARKET_DATA_RESEARCH_ENABLED", "false").lower() == "true"
    if market_research and environment not in {"development", "staging"}:
        raise ValueError("Market-data research requires isolated development or staging")
    market_provider = os.getenv("MARKET_DATA_PROVIDER", "yahoo").lower()
    if market_provider not in {"yahoo", "upstox"}:
        raise ValueError("Unknown market-data provider")
    return Settings(environment, demo, token_hash, database_url, auth_mode, cidrs, market_research, market_provider)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
