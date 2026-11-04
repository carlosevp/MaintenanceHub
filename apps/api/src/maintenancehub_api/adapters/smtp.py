"""SMTP transport + log sink when SMTP_ENABLED=false (ADR-004 / ADR-012)."""

from __future__ import annotations

import logging
import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage

from maintenancehub_api.config import get_settings

logger = logging.getLogger("maintenancehub.smtp")


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str | None = None
    error: str | None = None
    channel: str = "log"


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
            return SendResult(ok=True, provider_message_id=msg_id, channel="log")

        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
            msg_id = message.get("Message-ID") or f"smtp-{uuid.uuid4().hex[:12]}"
            return SendResult(ok=True, provider_message_id=msg_id, channel="smtp")
        except Exception as exc:  # noqa: BLE001
            logger.exception("SMTP send failed")
            return SendResult(ok=False, error=str(exc), channel="smtp")


def get_smtp_adapter() -> SmtpAdapter:
    return SmtpAdapter()
