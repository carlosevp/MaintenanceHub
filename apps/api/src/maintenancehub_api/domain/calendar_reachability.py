"""Assess whether an ICS subscription URL is reachable from Microsoft cloud."""

from __future__ import annotations

from urllib.parse import urlparse


def assess_public_base_url(base_url: str | None) -> dict[str, object]:
    """Return honest Outlook-on-the-web reachability guidance.

    Outlook on the web fetches ICS from Microsoft's cloud — localhost,
    loopback, and typical internal-only OpenShift/service DNS are not reachable
    from that path. Corporate browsers reaching the same URL does not imply
    Outlook web can subscribe.
    """
    raw = (base_url or "").strip()
    result: dict[str, object] = {
        "base_url": raw or None,
        "configured": bool(raw),
        "https": False,
        "microsoft_cloud_reachable": False,
        "subscription_supported": False,
        "code": "missing",
        "message": (
            "No public HTTPS base URL is configured (PUBLIC_BASE_URL). "
            "Outlook on the web cannot subscribe to an unreachable feed. "
            "Use Download calendar (.ics) instead, or set a browser-appropriate "
            "HTTPS URL reachable from Microsoft cloud."
        ),
    }
    if not raw:
        return result

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    scheme = (parsed.scheme or "").lower()
    result["https"] = scheme == "https"

    internal_hosts = {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
    }
    internal_suffixes = (
        ".svc",
        ".svc.cluster.local",
        ".internal",
        ".local",
        ".corp",
        ".lan",
    )

    if not host:
        result["code"] = "invalid"
        result["message"] = (
            "PUBLIC_BASE_URL is invalid. Fix the configured HTTPS base URL, "
            "or use Download calendar (.ics) for a static snapshot."
        )
        return result

    if host in internal_hosts or any(host.endswith(suf) for suf in internal_suffixes):
        result["code"] = "internal_only"
        result["message"] = (
            f"The calendar feed base URL ({raw}) points at a localhost or internal host. "
            "Outlook on the web fetches from Microsoft cloud and generally cannot reach "
            "it — even when a corporate browser can. MaintenanceHub does not expose an "
            "internal proxy. Keep the tokenized subscription for clients that can reach "
            "this URL, or use Download calendar (.ics)."
        )
        return result

    if scheme != "https":
        result["code"] = "not_https"
        result["message"] = (
            f"The calendar feed base URL ({raw}) is not HTTPS. Outlook on the web "
            "typically requires a publicly reachable HTTPS feed. Use Download "
            "calendar (.ics) or configure PUBLIC_BASE_URL to an HTTPS endpoint "
            "reachable from Microsoft cloud."
        )
        return result

    result["microsoft_cloud_reachable"] = True
    result["subscription_supported"] = True
    result["code"] = "ok"
    result["message"] = (
        "Subscription feed URL uses HTTPS on a non-local host. Outlook clients that "
        "can reach this URL may refresh the feed; refresh is client-poll only."
    )
    return result
