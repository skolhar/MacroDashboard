"""Provision and revoke identifiable, scoped operator credentials offline."""
import argparse
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from packages.domain.models import OperatorCredential
from packages.domain.settings import token_digest
from packages.domain.store import engine

SCOPES = {"imports:write", "ingestion:run"}


def issue(session: Session, operator_id: str, scopes: set[str], days: int, token: str | None = None) -> str:
    if not operator_id or len(operator_id) > 100 or not scopes or not scopes <= SCOPES or not 1 <= days <= 90:
        raise ValueError("Invalid operator, scopes or expiry")
    token = token or secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    session.add(OperatorCredential(token_hash=token_digest(token), operator_id=operator_id, scopes=",".join(sorted(scopes)), created_at=now, expires_at=now + timedelta(days=days)))
    session.commit()
    return token


def revoke(session: Session, token_hash: str) -> bool:
    credential = session.get(OperatorCredential, token_hash)
    if not credential or credential.revoked_at:
        return False
    credential.revoked_at = datetime.now(timezone.utc)
    session.commit()
    return True


def main():
    parser = argparse.ArgumentParser(description="Manage SmartHedge operator credentials")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("issue")
    add.add_argument("operator_id")
    add.add_argument("--scopes", required=True, help="Comma-separated scopes")
    add.add_argument("--days", type=int, default=30)
    disable = commands.add_parser("revoke")
    disable.add_argument("token_hash", help="SHA-256 digest shown by list; never pass raw token on command line")
    commands.add_parser("list")
    args = parser.parse_args()
    with Session(engine()) as session:
        if args.command == "issue":
            token = issue(session, args.operator_id, set(args.scopes.split(",")), args.days)
            print("Store this token securely; it is shown once:\n" + token)
        elif args.command == "revoke":
            print("revoked" if revoke(session, args.token_hash) else "not found or already revoked")
        else:
            for credential in session.scalars(select(OperatorCredential).order_by(OperatorCredential.operator_id)):
                print(credential.operator_id, credential.token_hash, credential.scopes, credential.expires_at.isoformat(), "revoked" if credential.revoked_at else "active")


if __name__ == "__main__":
    main()
