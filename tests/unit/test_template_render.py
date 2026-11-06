"""M19 template rendering — placeholders, HTML escape, sanitize."""

from maintenancehub_api.domain.templates import (
    DEFAULT_TEMPLATES,
    render_template,
    sanitize_html_fragment,
    sample_context,
)


def test_double_and_single_brace_placeholders():
    ctx = {"title": "Claims window", "status": "in_progress"}
    assert render_template("{{title}} / {status}", ctx) == "Claims window / in_progress"


def test_html_escape_on_values_not_markup():
    ctx = {"title": "<script>x</script>"}
    out = render_template("<p>{{title}}</p>", ctx, html_escape=True)
    assert "<script>" not in out
    assert "&lt;script&gt;x&lt;/script&gt;" in out
    assert out.startswith("<p>")


def test_sanitize_strips_script_and_handlers():
    dirty = '<p onclick="alert(1)">Hi</p><script>bad()</script><a href="javascript:alert(1)">x</a>'
    clean = sanitize_html_fragment(dirty)
    assert "script" not in clean.lower() or "<script" not in clean.lower()
    assert "onclick" not in clean.lower()
    assert "javascript:" not in clean.lower()


def test_pa_teams_alert_defaults():
    pa = DEFAULT_TEMPLATES["pa.teams_alert"]
    assert pa["subject"] == "[TEAMS] Maintenance Alert"
    assert "To: {{teams_target_email}}" in pa["body"]
    ctx = sample_context()
    rendered = render_template(pa["body"], ctx)
    assert rendered.startswith("To: ops-payments-channel@example.com")
    assert "Power Automate" in rendered
