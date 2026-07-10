"""Encrypt, store, and resolve org-owned provider keys.

Keys are Fernet-encrypted with ``KEY_ENCRYPTION_SECRET`` before they touch the
database, and the plaintext is only ever reconstructed server-side at the
moment a chat turn needs it (``resolve_org_key``). Nothing here logs or returns
key material; the API surface exposes only ``{provider, last4, set_at}``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from northwind_copilot.core.config import settings
from northwind_copilot.tenancy.models import ApiKey


class KeyEncryptionUnavailable(RuntimeError):
    """Raised when ``KEY_ENCRYPTION_SECRET`` is missing or malformed."""


def _fernet() -> Fernet:
    """Build the Fernet cipher from settings, or raise a clean error."""
    secret = settings.key_encryption_secret
    if not secret:
        raise KeyEncryptionUnavailable(
            "KEY_ENCRYPTION_SECRET is not configured; cannot store provider keys."
        )
    try:
        return Fernet(secret.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise KeyEncryptionUnavailable(
            "KEY_ENCRYPTION_SECRET is not a valid Fernet key."
        ) from exc


async def store_key(
    session: AsyncSession, *, org_id: str, provider: str, plaintext: str
) -> ApiKey:
    """Encrypt and upsert one provider key for an org.

    Args:
        session: An open application-database session.
        org_id: The owning org.
        provider: The provider the key belongs to (``openai``/``openrouter``).
        plaintext: The key as entered by the user. Never persisted or logged.

    Returns:
        The stored (or updated) row.
    """
    encrypted = _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    row = await session.get(ApiKey, (org_id, provider))
    if row is None:
        row = ApiKey(org_id=org_id, provider=provider)
        session.add(row)
    row.encrypted_key = encrypted
    row.last4 = plaintext[-4:]
    row.set_at = datetime.now(timezone.utc)
    await session.flush()
    return row


async def delete_key(session: AsyncSession, *, org_id: str, provider: str) -> bool:
    """Remove one provider key. Returns whether a key existed."""
    row = await session.get(ApiKey, (org_id, provider))
    if row is None:
        return False
    await session.delete(row)
    return True


async def list_keys(session: AsyncSession, org_id: str) -> list[ApiKey]:
    """Return the org's stored key rows (metadata only is exposed upstream)."""
    from sqlalchemy import select

    return list(
        (
            await session.execute(
                select(ApiKey).where(ApiKey.org_id == org_id).order_by(ApiKey.provider)
            )
        ).scalars()
    )


async def resolve_org_key(
    session: AsyncSession, *, org_id: str, provider: str
) -> str | None:
    """Decrypt and return the org's key for a provider, if one is stored.

    A row that fails to decrypt (e.g. after a KEK rotation without
    re-encryption) resolves to ``None`` rather than erroring the chat turn —
    the request then falls through to the metered path.
    """
    row = await session.get(ApiKey, (org_id, provider))
    if row is None:
        return None
    try:
        return _fernet().decrypt(row.encrypted_key.encode("ascii")).decode("utf-8")
    except (KeyEncryptionUnavailable, InvalidToken):
        return None
