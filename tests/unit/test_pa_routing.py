"""M19 harden — PA routing contract extract/validate/envelope."""

from maintenancehub_api.domain.pa_routing import (
    PA_SUBJECT,
    apply_pa_contract,
    assert_smtp_to_differs_from_route,
    extract_rendered_routing,
    extract_routing_from_html,
    extract_routing_from_plain,
    validate_pa_extractable,
)
from maintenancehub_api.domain.notifications import resolve_lifecycle_template_key
from maintenancehub_api.domain.template_manager import resolve_active_template
from maintenancehub_api.domain.templates import DEFAULT_TEMPLATES


def test_extract_plain_and_html():
    plain = DEFAULT_TEMPLATES["pa.teams_alert"]["body"]
    html = DEFAULT_TEMPLATES["pa.teams_alert"]["body_html"]
    assert extract_routing_from_plain(plain) == "{{teams_target_email}}"
    assert extract_routing_from_html(html) == "{{teams_target_email}}"


def test_apply_contract_restores_stripped_routing():
    out = apply_pa_contract(
        key="pa.teams_alert",
        channel="bridge",
        subject_template="oops",
        body_plain="Title: {{title}}\n",
        body_html="<p>{{title}}</p>",
    )
    assert out["subject_template"] == PA_SUBJECT
    assert out["body_plain_template"].startswith("To: {{teams_target_email}}")
    assert extract_routing_from_html(out["body_html_template"] or "")


def test_validate_and_smtp_differs():
    pa = DEFAULT_TEMPLATES["pa.teams_alert"]
    ok = validate_pa_extractable(
        subject_template=pa["subject"],
        body_plain=pa["body"],
        body_html=pa["body_html"],
        context={"teams_target_email": "channel@contoso.com", "smtp_to": "bridge@example.com"},
    )
    assert ok["ok"], ok["errors"]
    assert ok["routing_email"] == "channel@contoso.com"
    rendered = extract_rendered_routing(
        body_plain=f"To: channel@contoso.com\n\nHi",
        body_html="<p><strong>To:</strong> channel@contoso.com</p>",
    )
    assert rendered == "channel@contoso.com"
    try:
        assert_smtp_to_differs_from_route(
            smtp_to="channel@contoso.com", routing_email="channel@contoso.com"
        )
        raise AssertionError("expected mismatch error")
    except ValueError:
        pass


def test_lifecycle_keys_cancel_complete_remind_extend():
    assert resolve_lifecycle_template_key("event.extended") == "event.extended"
    assert resolve_lifecycle_template_key("event.reminder") == "event.reminder"
    assert resolve_lifecycle_template_key("event.cancelled") == "event.transitioned"
    assert resolve_lifecycle_template_key("event.completed") == "event.transitioned"
    assert (
        resolve_lifecycle_template_key("event.transitioned", to_status="cancelled")
        == "event.transitioned"
    )


def test_resolve_active_deterministic(db_session):
    from maintenancehub_api.domain.template_manager import ensure_default_templates, create_template

    ensure_default_templates(db_session)
    # Two active customs for same event_type — lowest key wins after exact-key miss
    create_template(
        db_session,
        actor_id=db_session.admin.id,
        key="z.late",
        name="Late",
        event_type="event.created",
        subject_template="Z",
        body_plain_template="z",
        activate=True,
    )
    create_template(
        db_session,
        actor_id=db_session.admin.id,
        key="a.early",
        name="Early",
        event_type="event.created",
        subject_template="A",
        body_plain_template="a",
        activate=True,
    )
    # Exact system key still preferred
    row = resolve_active_template(db_session, "event.created")
    assert row is not None
    assert row.key == "event.created"
