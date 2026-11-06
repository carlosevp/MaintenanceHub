"""Power Automate Teams routing contract (M19 harden).

SMTP To = bridge mailbox (envelope).
Body ``To: <email>`` = Teams routing for the PA flow (never the SMTP To).
Subject trigger = ``[TEAMS] Maintenance Alert``.
"""

from __future__ import annotations

import re
from typing import Any

from maintenancehub_api.domain.templates import render_template, sample_context

PA_SUBJECT = "[TEAMS] Maintenance Alert"
PA_ROUTING_PLACEHOLDER = "{{teams_target_email}}"
PA_ROUTING_PLAIN_LINE = f"To: {PA_ROUTING_PLACEHOLDER}"
PA_ROUTING_HTML_SNIPPET = f"<p><strong>To:</strong> {PA_ROUTING_PLACEHOLDER}</p>"

# Plain: first line "To: email" (placeholder or literal)
_PLAIN_TO_RE = re.compile(
    r"(?im)^\s*To:\s*(\{\{\s*teams_target_email\s*\}\}|[^\s<>]+@[^\s<>]+)\s*$"
)
# HTML: <strong>To:</strong> … email/placeholder (after tags stripped-ish)
_HTML_TO_RE = re.compile(
    r"(?is)<strong>\s*To:\s*</strong>\s*(\{\{\s*teams_target_email\s*\}\}|[^<\s]+@[^<\s]+)"
)
_HTML_TO_LOOSE_RE = re.compile(
    r"(?is)\bTo:\s*(?:</?(?:strong|b|span)[^>]*>\s*)*"
    r"(\{\{\s*teams_target_email\s*\}\}|[^<\s]+@[^<\s]+)"
)
_RENDERED_PLAIN_TO_RE = re.compile(r"(?im)^\s*To:\s*([^\s<>]+@[^\s<>]+)\s*$")
_RENDERED_HTML_TO_RE = re.compile(
    r"(?is)<strong>\s*To:\s*</strong>\s*([^<\s]+@[^<\s]+)"
)


def is_pa_template(
    *,
    key: str | None = None,
    channel: str | None = None,
    subject_template: str | None = None,
    body_plain: str | None = None,
) -> bool:
    if (key or "").startswith("pa."):
        return True
    if (channel or "") == "bridge":
        return True
    if (subject_template or "").strip() == PA_SUBJECT:
        return True
    if body_plain and _PLAIN_TO_RE.search(body_plain):
        return True
    return False


def extract_routing_from_plain(text: str) -> str | None:
    m = _PLAIN_TO_RE.search(text or "")
    return m.group(1).strip() if m else None


def extract_routing_from_html(html: str) -> str | None:
    if not html:
        return None
    m = _HTML_TO_RE.search(html) or _HTML_TO_LOOSE_RE.search(html)
    return m.group(1).strip() if m else None


def extract_rendered_routing(*, body_plain: str, body_html: str = "") -> str | None:
    m = _RENDERED_PLAIN_TO_RE.search(body_plain or "")
    if m:
        return m.group(1).strip()
    m = _RENDERED_HTML_TO_RE.search(body_html or "")
    if m:
        return m.group(1).strip()
    # Fallback: plain extractor after render may still match literal emails
    return extract_routing_from_plain(body_plain) or extract_routing_from_html(body_html)


def ensure_plain_routing_envelope(body_plain: str) -> str:
    """Guarantee the canonical first-line routing contract in plain body."""
    text = (body_plain or "").lstrip("\ufeff")
    if extract_routing_from_plain(text):
        # Normalize first matching line to canonical placeholder form when it's the placeholder
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if re.match(r"(?i)^\s*To:\s*", line):
                lines[i] = PA_ROUTING_PLAIN_LINE
                # Drop leading blank lines before To:
                while i > 0 and not lines[0].strip():
                    lines.pop(0)
                    i -= 1
                rest = "\n".join(lines)
                if not rest.endswith("\n"):
                    rest += "\n"
                return rest
    # Prepend canonical routing block
    content = text.lstrip()
    if content:
        return f"{PA_ROUTING_PLAIN_LINE}\n\n{content}"
    return f"{PA_ROUTING_PLAIN_LINE}\n\n"


def ensure_html_routing_envelope(body_html: str | None) -> str | None:
    if body_html is None or body_html.strip() == "":
        return None
    if extract_routing_from_html(body_html):
        # Replace first To: value with placeholder for contract stability
        def _repl(m: re.Match[str]) -> str:
            return m.group(0).replace(m.group(1), PA_ROUTING_PLACEHOLDER)

        return _HTML_TO_RE.sub(_repl, body_html, count=1) if _HTML_TO_RE.search(body_html) else (
            _HTML_TO_LOOSE_RE.sub(_repl, body_html, count=1)
        )
    return f"{PA_ROUTING_HTML_SNIPPET}\n{body_html}"


def apply_pa_contract(
    *,
    key: str,
    channel: str,
    subject_template: str,
    body_plain: str,
    body_html: str | None,
    force: bool | None = None,
) -> dict[str, Any]:
    """Normalize PA templates: fixed subject + extractable routing in plain/HTML."""
    apply = force if force is not None else is_pa_template(
        key=key, channel=channel, subject_template=subject_template, body_plain=body_plain
    )
    if not apply:
        return {
            "subject_template": subject_template,
            "body_plain_template": body_plain,
            "body_html_template": body_html,
            "pa_contract": False,
        }
    plain = ensure_plain_routing_envelope(body_plain)
    html = ensure_html_routing_envelope(body_html)
    return {
        "subject_template": PA_SUBJECT,
        "body_plain_template": plain,
        "body_html_template": html,
        "pa_contract": True,
    }


def validate_pa_extractable(
    *,
    subject_template: str,
    body_plain: str,
    body_html: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate subject + that rendered plain/HTML yield the same routing email."""
    errors: list[str] = []
    if subject_template.strip() != PA_SUBJECT:
        errors.append(f"PA subject must be exactly {PA_SUBJECT!r}")
    if not extract_routing_from_plain(body_plain):
        errors.append("Plain body must include extractable line `To: {{teams_target_email}}`")
    if body_html and not extract_routing_from_html(body_html):
        errors.append("HTML body must include extractable `To:` + teams_target_email")

    ctx = sample_context()
    if context:
        ctx.update(context)
    if not ctx.get("teams_target_email"):
        ctx["teams_target_email"] = "route-check@example.com"

    rendered_plain = render_template(body_plain, ctx, html_escape=False)
    rendered_html = (
        render_template(body_html, ctx, html_escape=True) if body_html else ""
    )
    route_plain = extract_rendered_routing(body_plain=rendered_plain, body_html="")
    route_html = (
        extract_rendered_routing(body_plain="", body_html=rendered_html) if body_html else route_plain
    )
    if not route_plain:
        errors.append("Rendered plain body does not yield a To: email")
    if body_html and not route_html:
        errors.append("Rendered HTML body does not yield a To: email")
    if route_plain and route_html and route_plain.lower() != route_html.lower():
        errors.append(
            f"Plain/HTML routing mismatch after render: {route_plain!r} vs {route_html!r}"
        )

    smtp_to = (context or {}).get("smtp_to") or (context or {}).get("bridge_mailbox")
    if smtp_to and route_plain and smtp_to.lower() == route_plain.lower():
        errors.append("SMTP To must not equal Teams routing address (body To:)")

    return {
        "ok": not errors,
        "errors": errors,
        "subject": PA_SUBJECT,
        "routing_email": route_plain,
        "smtp_to": smtp_to,
        "rendered_plain_head": "\n".join(rendered_plain.splitlines()[:4]),
    }


def assert_smtp_to_differs_from_route(*, smtp_to: str, routing_email: str | None) -> None:
    if not routing_email:
        return
    if smtp_to.strip().lower() == routing_email.strip().lower():
        raise ValueError(
            "SMTP envelope To must differ from Power Automate body routing To: "
            f"{routing_email!r}"
        )
