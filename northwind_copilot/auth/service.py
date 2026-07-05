"""Password hashing and JWT session tokens.

Passwords are hashed with argon2id (memory-hard, the current OWASP default).
Sessions are stateless JWTs signed with ``settings.jwt_secret`` and delivered as
an httpOnly cookie, so the token is never readable by JavaScript (no
localStorage exposure to XSS).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from northwind_copilot.core.config import settings

_ph = PasswordHasher()

COOKIE_NAME = "nw_session"
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Return an argon2id hash of ``password``."""
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return whether ``password`` matches ``password_hash``."""
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def mint_session_token(user_id: str) -> str:
    """Create a signed JWT session token for ``user_id``.

    Args:
        user_id: The authenticated user's id.

    Returns:
        An encoded JWT with ``sub`` and an expiry.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def read_session_token(token: str) -> str | None:
    """Verify a session token and return its user id, or ``None`` if invalid.

    Args:
        token: The encoded JWT from the session cookie.

    Returns:
        The ``sub`` (user id) claim on success; ``None`` when the token is
        expired, tampered with, or otherwise invalid.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None
