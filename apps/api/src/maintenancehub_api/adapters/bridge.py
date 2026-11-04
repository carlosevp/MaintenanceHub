"""Power Automate email bridge — Teams-channel destinations via email only (ADR-004).

No Teams SDK, Graph API, or incoming webhooks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from maintenancehub_api.adapters.smtp import SendResult, get_smtp_adapter
from maintenancehub_api.config import get_settings

logger = logging.getLogger("maintenancehub.bridge")


@dataclass
class BridgeRoute:
    channel_key: str
    title: str


def render_bridge_subject(*, channel_key: str, title: str) -> str:
    settings = get_settings()
    return settings.bridge_subject_template.format(
        channel_key=channel_key,
        title=title,
    )


class BridgeAdapter:
    """Sends to the configured bridge mailbox with routing tokens in the subject."""

    def send(
        self,
        *,
        channel_key: str,
        title: str,
        body: str,
        mailbox: str | None = None,
    ) -> SendResult:
        settings = get_settings()
        if not settings.bridge_enabled and not settings.smtp_enabled:
            # Still allow log-sink path for local demo
            pass
        if not settings.bridge_enabled and settings.smtp_enabled:
            return SendResult(
                ok=False,
                error="BRIDGE_ENABLED=false — Teams via email bridge is disabled",
                channel="bridge",
            )

        to = mailbox or settings.bridge_mailbox
        if not to:
            # Fall back to log sink destination label
            to = settings.bridge_mailbox or "bridge-mailbox@example.com"

        subject = render_bridge_subject(channel_key=channel_key, title=title)
        logger.info(
            "Bridge send (Teams via email bridge) mailbox=%s subject=%r",
            to,
            subject,
        )
        # Reuse SMTP path; when SMTP disabled, log sink still records the bridged subject
        result = get_smtp_adapter().send(to=to, subject=subject, body=body)
        result.channel = "bridge"
        return result

    def connection_test(self) -> dict:
        settings = get_settings()
        return {
            "bridge_enabled": settings.bridge_enabled,
            "mailbox": settings.bridge_mailbox or None,
            "subject_template": settings.bridge_subject_template,
            "smtp_enabled": settings.smtp_enabled,
            "note": (
                "Teams via email bridge — no Teams API or webhooks. "
                "Customer Power Automate flow must parse subject routing tokens."
            ),
            "ok": bool(settings.bridge_mailbox) or not settings.bridge_enabled,
        }


def get_bridge_adapter() -> BridgeAdapter:
    return BridgeAdapter()
