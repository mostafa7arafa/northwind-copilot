"""Error tracking (Sentry) for the hosted service.

Opt-in via ``SENTRY_DSN`` and safe to run without the SDK installed (the POC
and the test suite never need it). Every outgoing event passes through a
scrubber that redacts provider-key and bearer-token shapes, so a stray key in
an exception message can never reach a third party.

The existing ``error_id`` correlation ids (from ``response.streaming``) are
attached as the ``error_id`` event tag — search Sentry by the id a user
reports.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Provider keys (sk-..., sk-or-..., etc.) and Authorization bearer values.
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{4,}|Bearer\s+[A-Za-z0-9._\-]+)")
_REDACTED = "[redacted]"


def _scrub_value(value: Any) -> Any:
    """Recursively redact secret-shaped substrings in an event payload."""
    if isinstance(value, str):
        return _SECRET_RE.sub(_REDACTED, value)
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(v) for v in value]
    return value


def _before_send(event: dict, hint: dict) -> dict:
    """Sentry ``before_send`` hook: redact key material everywhere."""
    return _scrub_value(event)


def init_sentry() -> bool:
    """Initialise Sentry when ``SENTRY_DSN`` is set and the SDK is installed.

    Returns:
        Whether Sentry is active.
    """
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed")
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        # Logs become breadcrumbs only; events come from explicit captures and
        # unhandled exceptions (the FastAPI integration is auto-enabled). This
        # avoids double-reporting every `logger.exception` call.
        integrations=[LoggingIntegration(event_level=None)],
        traces_sample_rate=0.0,
        send_default_pii=False,
        before_send=_before_send,
    )
    return True


def report_error(exc: BaseException, *, error_id: str) -> None:
    """Send one exception to Sentry, tagged with its correlation id.

    A no-op when Sentry isn't configured — callers never need to guard.
    """
    try:
        import sentry_sdk

        if sentry_sdk.get_client().is_active():
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("error_id", error_id)
                sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001 - error reporting must never break chat
        logger.debug("sentry capture failed", exc_info=True)
