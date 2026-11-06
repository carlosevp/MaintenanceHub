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
    # True when the provider may have accepted the message but the client lost
    # confirmation (timeout / dropped connection after send). Callers must NOT
    # auto-retry — that would risk duplicate delivery.
    uncertain: bool = False


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
