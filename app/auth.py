"""Email + password authentication -- docs/07_non_functional_requirements.md.

Single role, no RBAC: any active user can use every endpoint. Passwords
are hashed locally with scrypt (Python stdlib -- no extra dependency, and
nothing here talks to an outside service). There's no self-registration
and no password-reset email (no outbound SMTP by design): accounts are
created and reset from the command line, see app/users.py.

Sessions are server-side rows keyed by a random token sent in an
HttpOnly, SameSite=Strict cookie. Only a SHA-256 of the token is stored,
so a database dump alone can't be replayed as a login.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserSession

SESSION_COOKIE = "dpr_session"

# scrypt cost parameters, stored in each hash so they can be raised later
# without invalidating existing passwords. n=2**14, r=8 is the commonly
# recommended interactive-login setting (~16 MiB, tens of ms on CPU).
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1

MIN_PASSWORD_LENGTH = 10


def session_lifetime() -> timedelta:
    return timedelta(hours=int(os.environ.get("SESSION_HOURS", "12")))


def cookie_secure() -> bool:
    # Off by default because the single-machine rollout serves plain HTTP
    # on the local network; turn on (COOKIE_SECURE=true) once it's behind
    # HTTPS, e.g. on the future shared server.
    return os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored_hash.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    expected = base64.b64decode(digest_b64)
    actual = hashlib.scrypt(
        password.encode(),
        salt=base64.b64decode(salt_b64),
        n=int(n),
        r=int(r),
        p=int(p),
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)


# Verified against when the email doesn't exist, so a login attempt for an
# unknown account takes as long as one for a real account with a wrong
# password -- response timing doesn't reveal which emails are registered.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.query(User).filter_by(email=normalize_email(email)).one_or_none()
    if user is None or not user.is_active:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    """Returns the raw token (for the cookie); only its hash is stored."""
    now = datetime.utcnow()
    # Opportunistic cleanup, cheap at this scale -- no separate cron needed.
    db.query(UserSession).filter(UserSession.expires_at < now).delete()

    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            expires_at=now + session_lifetime(),
        )
    )
    db.commit()
    return token


def delete_session(db: Session, token: str) -> None:
    db.query(UserSession).filter_by(token_hash=_token_hash(token)).delete()
    db.commit()


def get_current_user(
    dpr_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency guarding every /api route except login."""
    if dpr_session:
        session = (
            db.query(UserSession)
            .filter_by(token_hash=_token_hash(dpr_session))
            .one_or_none()
        )
        if (
            session is not None
            and session.expires_at > datetime.utcnow()
            and session.user.is_active
        ):
            return session.user
    raise HTTPException(status_code=401, detail="not authenticated")
