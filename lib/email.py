"""Email helpers for scoutVISION Sandbox."""

from __future__ import annotations

import resend

from settings import EMAIL_FROM, RESEND_API_KEY


def send_email(
    *,
    subject: str,
    text: str,
    to: list[str],
    html: str | None = None,
    from_addr: str | None = None,
) -> object:
    """Send an email via Resend."""
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY is not configured")
    if not to:
        raise RuntimeError("No email recipients configured")

    resend.api_key = RESEND_API_KEY
    payload = {
        "from": from_addr or EMAIL_FROM,
        "to": to,
        "subject": subject,
        "text": text,
    }
    if html:
        payload["html"] = html

    return resend.Emails.send(payload)
