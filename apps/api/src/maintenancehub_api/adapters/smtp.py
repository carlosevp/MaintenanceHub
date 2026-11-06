"""SMTP transport + log sink when SMTP_ENABLED=false (ADR-004 / ADR-012).

When MH_NOTIFICATION_CAPTURE_DIR is set (demo), each send is also written as a
JSON file under that directory so demos need no real SMTP.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from maintenancehub_api.config import get_settings

logger = logging.getLogger("maintenancehub.smtp")


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str | None = None
    error: str | None = None
    channel: str = "log"
    # True when the provider may have accepted the message but the client lost
    # confirmation (timeout / dropped connection after send). Callers must NOT
    # auto-retry — that would risk duplicate delivery.
    uncertain: bool = False


def _capture_notification(*, to: str, subject: str, body: str, msg_id: str, channel: str) -> None:
    """Write a captured notification for local demos (no SMTP required)."""
    raw = os.environ.get("MH_NOTIFICATION_CAPTURE_DIR", "").strip()
    if not raw:
        return
    try:
        dest = Path(raw)
        dest.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = dest / f"{stamp}-{msg_id}.json"
        path.write_text(
            json.dumps(
                {
                    "id": msg_id,
                    "channel": channel,
                    "to": to,
                    "subject": subject,
                    "body": body,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        logger.exception("Failed to capture notification under %s", raw)


class SmtpAdapter:
    def send(self, *, to: str, subject: str, body: str) -> SendResult:
        settings = get_settings()
        if not settings.smtp_enabled:
            msg_id = f"log-{uuid.uuid4().hex[:12]}"
            logger.info(
                "[SMTP_DISABLED log sink] to=%s subject=%r body=%r id=%s",
                to,
                subject,
                body[:500],
                msg_id,
            )
            _capture_notification(
                to=to, subject=subject, body=body, msg_id=msg_id, channel="log"
            )
            return SendResult(ok=True, provider_message_id=msg_id, channel="log")

        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        handed_off = False
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                # After send_message returns, SMTP has accepted the DATA payload.
                # A subsequent timeout (e.g. on QUIT) is treated as uncertain —
                # the message may already be queued at the relay.
                smtp.send_message(message)
                handed_off = True
            msg_id = message.get("Message-ID") or f"smtp-{uuid.uuid4().hex[:12]}"
            _capture_notification(
                to=to, subject=subject, body=body, msg_id=str(msg_id), channel="smtp"
            )
            return SendResult(ok=True, provider_message_id=msg_id, channel="smtp")
        except Exception as exc:  # noqa: BLE001
            logger.exception("SMTP send failed (handed_off=%s)", handed_off)
            if handed_off:
                return SendResult(
                    ok=True,
                    uncertain=True,
                    provider_message_id=f"uncertain-smtp-{uuid.uuid4().hex[:12]}",
                    error=f"UNCERTAIN: SMTP accepted payload; response lost ({exc})",
                    channel="smtp",
                )
            return SendResult(ok=False, error=str(exc), channel="smtp")


def get_smtp_adapter() -> SmtpAdapter:
    return SmtpAdapter()
