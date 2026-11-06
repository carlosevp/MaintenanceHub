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
    """Sends to the configured bridge mailbox with routing tokens in subject and/or body."""

    def send(
        self,
        *,
        channel_key: str,
        title: str,
        body: str,
        mailbox: str | None = None,
        subject: str | None = None,
        body_html: str | None = None,
        force_capture: bool = False,
    ) -> SendResult:
        settings = get_settings()
        if not settings.bridge_enabled and not settings.smtp_enabled and not force_capture:
            # Still allow log-sink path for local demo
            pass
        if (
            not settings.bridge_enabled
            and settings.smtp_enabled
            and not force_capture
        ):
            return SendResult(
                ok=False,
                error="BRIDGE_ENABLED=false — Teams via email bridge is disabled",
                channel="bridge",
            )

        # Envelope To is always the configured bridge mailbox when set.
        # Subscription destination must not override PA routing (body To:).
        to = settings.bridge_mailbox or mailbox or "bridge-mailbox@example.com"

        final_subject = subject if subject is not None else render_bridge_subject(
            channel_key=channel_key, title=title
        )
        logger.info(
            "Bridge send (Teams via email bridge) mailbox=%s subject=%r",
            to,
            final_subject,
        )
        # Reuse SMTP path; when SMTP disabled / capture-only, never dials external SMTP.
        # SMTP To = bridge mailbox. Body may contain `To: <email>` for Power Automate routing.
        result = get_smtp_adapter().send(
            to=to,
            subject=final_subject,
            body=body,
            body_html=body_html,
            force_capture=force_capture,
        )
        result.channel = "capture" if force_capture else "bridge"
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
                "Customer Power Automate flow must parse subject routing tokens "
                "and/or body `To: <email>` lines (PA template manager)."
            ),
            "ok": bool(settings.bridge_mailbox) or not settings.bridge_enabled,
        }


def get_bridge_adapter() -> BridgeAdapter:
    return BridgeAdapter()
