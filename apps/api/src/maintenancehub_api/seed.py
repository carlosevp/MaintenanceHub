"""Labeled demo data for local_dev. Safe to re-run (idempotent on keys/emails)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from maintenancehub_api.auth.security import hash_password
from maintenancehub_api.domain import events as event_service
from maintenancehub_api.domain.notifications import ensure_default_templates
from maintenancehub_api.domain.authz import grant_user_on_application
from maintenancehub_api.models import (
    AppEnvironment,
    Application,
    Dependency,
    DependencyOrigin,
    EventStatus,
    Environment,
    ExternalCiLink,
    Favorite,
    GroupRoleMapping,
    InfraComponent,
    ReminderOffset,
    Role,
    RoleName,
    Subscription,
    SubscriptionTarget,
    SupportGroup,
    Tag,
    Tagging,
    User,
    UserRole,
)


DEMO_PASSWORD = "password123"

SEED_USERS = [
    ("viewer@demo.example.com", "Demo Viewer", [RoleName.viewer]),
    ("publisher@demo.example.com", "Demo Publisher", [RoleName.publisher]),
    ("owner@demo.example.com", "Demo App Owner", [RoleName.application_owner]),
    ("admin@demo.example.com", "Demo Platform Admin", [RoleName.platform_administrator]),
]


def seed_demo(db: Session) -> None:
    # Roles
    roles: dict[RoleName, Role] = {}
    for name in RoleName:
        role = db.query(Role).filter(Role.name == name).first()
        if not role:
            role = Role(name=name)
            db.add(role)
            db.flush()
        roles[name] = role

    # Users
    users: dict[str, User] = {}
    for email, display, role_names in SEED_USERS:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                email=email,
                display_name=display,
                password_hash=hash_password(DEMO_PASSWORD),
                is_active=True,
            )
            db.add(user)
            db.flush()
            for rn in role_names:
                db.add(UserRole(user_id=user.id, role_id=roles[rn].id))
        users[email] = user

    # Environments
    env_defs = [
        ("DEV", "Development", 10),
        ("INT", "Integration", 20),
        ("QA", "QA", 30),
        ("UAT", "UAT", 40),
        ("PROD", "Production", 50),
        ("NON-PROD", "Non-Production shared", 15),
    ]
    envs: dict[str, Environment] = {}
    for key, name, sort in env_defs:
        env = db.query(Environment).filter(Environment.key == key).first()
        if not env:
            env = Environment(key=key, name=name, sort_order=sort)
            db.add(env)
            db.flush()
        envs[key] = env

    # Support group
    sg = db.query(SupportGroup).filter(SupportGroup.key == "platform-ops").first()
    if not sg:
        sg = SupportGroup(key="platform-ops", name="[DEMO] Platform Operations")
        db.add(sg)
        db.flush()

    # Applications with differently named envs
    apps_spec = [
        (
            "payments-gateway",
            "[DEMO] Payments Gateway",
            "Core payment processing API",
            [("DEV", "Payments-Dev"), ("PROD", "Payments-Production")],
        ),
        (
            "hr-portal",
            "[DEMO] HR Portal",
            "Employee self-service portal",
            [("QA", "HR-QA"), ("PROD", "HR-Live")],
        ),
        (
            "inventory-svc",
            "[DEMO] Inventory Service",
            "Warehouse inventory microservice",
            [("INT", "Inv-INT"), ("UAT", "Inv-UAT"), ("PROD", "Inv-PROD")],
        ),
        (
            "claims",
            "[DEMO] Claims",
            "Claims adjudication (M14 impact analysis consumer)",
            [("INT", "Claims-INT"), ("DEV", "Claims-DEV")],
        ),
        (
            "billing",
            "[DEMO] Billing",
            "Billing engine (M14 impact analysis consumer)",
            [("DEV", "Billing-DEV"), ("INT", "Billing-INT")],
        ),
        (
            "member-api",
            "[DEMO] Member API",
            "Member profile API (depends on Oracle; used transitively)",
            [("QA", "Member-QA"), ("INT", "Member-INT")],
        ),
        (
            "portal-bff",
            "[DEMO] Portal BFF",
            "BFF that depends on Member API (transitive Oracle impact)",
            [("QA", "Portal-QA")],
        ),
    ]
    apps: dict[str, Application] = {}
    for key, name, desc, app_envs in apps_spec:
        app = db.query(Application).filter(Application.key == key).first()
        if not app:
            app = Application(key=key, name=name, description=desc)
            db.add(app)
            db.flush()
            for env_key, display in app_envs:
                db.add(
                    AppEnvironment(
                        application_id=app.id,
                        environment_id=envs[env_key].id,
                        display_name=display,
                    )
                )
        apps[key] = app

    # Application-scoped grants for publisher / owner (enforced on event writes)
    publisher = users["publisher@demo.example.com"]
    owner = users["owner@demo.example.com"]
    for app in apps.values():
        grant_user_on_application(
            db, user_id=publisher.id, application_id=app.id, role=RoleName.publisher.value
        )
        grant_user_on_application(
            db, user_id=owner.id, application_id=app.id, role=RoleName.application_owner.value
        )

    # Tags + realistic manual dependency (payments → inventory)
    for tag_key, tag_name in (("tier1", "Tier-1"), ("customer-facing", "Customer-facing")):
        tag = db.query(Tag).filter(Tag.key == tag_key).first()
        if not tag:
            tag = Tag(key=tag_key, name=f"[DEMO] {tag_name}")
            db.add(tag)
            db.flush()
        for app_key in ("payments-gateway", "hr-portal"):
            exists = (
                db.query(Tagging)
                .filter(
                    Tagging.tag_id == tag.id,
                    Tagging.subject_type == "application",
                    Tagging.subject_id == apps[app_key].id,
                )
                .first()
            )
            if not exists:
                db.add(
                    Tagging(
                        tag_id=tag.id,
                        subject_type="application",
                        subject_id=apps[app_key].id,
                    )
                )

    dep = (
        db.query(Dependency)
        .filter(
            Dependency.from_type == "application",
            Dependency.from_id == apps["payments-gateway"].id,
            Dependency.to_type == "application",
            Dependency.to_id == apps["inventory-svc"].id,
        )
        .first()
    )
    if not dep:
        db.add(
            Dependency(
                from_type="application",
                from_id=apps["payments-gateway"].id,
                to_type="application",
                to_id=apps["inventory-svc"].id,
                dependency_kind="depends_on",
                origin=DependencyOrigin.manual.value,
            )
        )

    db.commit()

    ensure_default_templates(db)

    # Viewer favorites for dashboard demos
    viewer = users["viewer@demo.example.com"]
    for app_key in ("payments-gateway", "hr-portal"):
        fav = (
            db.query(Favorite)
            .filter(
                Favorite.user_id == viewer.id,
                Favorite.application_id == apps[app_key].id,
            )
            .first()
        )
        if not fav:
            db.add(Favorite(user_id=viewer.id, application_id=apps[app_key].id))
    db.commit()

    publisher = users["publisher@demo.example.com"]
    # Demo subscription: Payments app, -24h and -1h reminders (SMTP log sink)
    sub = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == publisher.id,
            Subscription.destination == "publisher@demo.example.com",
        )
        .first()
    )
    if not sub:
        sub = Subscription(
            user_id=publisher.id,
            destination_type="email_address",
            destination="publisher@demo.example.com",
            digest_mode="none",
            is_active=True,
        )
        db.add(sub)
        db.flush()
        db.add(
            SubscriptionTarget(
                subscription_id=sub.id,
                target_type="application",
                target_id=apps["payments-gateway"].id,
            )
        )
        for offset in (-1440, -60):
            db.add(ReminderOffset(subscription_id=sub.id, offset_minutes=offset))
        # Teams via email bridge example destination
        bridge_sub = Subscription(
            user_id=publisher.id,
            destination_type="teams_bridge_channel",
            destination="bridge-mailbox@example.com",
            bridge_channel_key="ops-payments",
            digest_mode="none",
            is_active=True,
        )
        db.add(bridge_sub)
        db.flush()
        db.add(
            SubscriptionTarget(
                subscription_id=bridge_sub.id,
                target_type="application",
                target_id=apps["payments-gateway"].id,
            )
        )
        db.commit()

    from maintenancehub_api.models import MaintenanceEvent

    # Demo events — only if none exist yet
    existing = (
        db.query(MaintenanceEvent)
        .filter(MaintenanceEvent.title.like("[DEMO]%"))
        .count()
    )
    if existing:
        return

    now = datetime.now(timezone.utc)

    # Current in-progress maintenance
    event_service.create_event(
        db,
        data={
            "kind": "planned_maintenance",
            "title": "[DEMO] Payments DB patch window",
            "description": "Apply security patches to primary Payments database.",
            "expected_impact": "Read-only for ~30 minutes",
            "approval_state": "confirmed_scheduled",
            "starts_at": now - timedelta(hours=1),
            "ends_at": now + timedelta(hours=2),
            "timezone": "America/Chicago",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": apps["payments-gateway"].id,
                    "environment_id": envs["PROD"].id,
                }
            ],
        },
        actor_id=publisher.id,
    )
    # Move to in_progress
    current = (
        db.query(MaintenanceEvent)
        .filter(MaintenanceEvent.title == "[DEMO] Payments DB patch window")
        .first()
    )
    if current:
        event_service.transition_event(
            db, current, target_status=EventStatus.in_progress, actor_id=publisher.id, note="Started"
        )

    # Upcoming confirmed
    event_service.create_event(
        db,
        data={
            "kind": "planned_maintenance",
            "title": "[DEMO] HR Portal TLS cert rotation",
            "description": "Rotate edge TLS certificates.",
            "expected_impact": "Brief 502s possible (<5 min)",
            "approval_state": "confirmed_scheduled",
            "starts_at": now + timedelta(days=2),
            "ends_at": now + timedelta(days=2, hours=1),
            "timezone": "America/Chicago",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": apps["hr-portal"].id,
                    "environment_id": envs["PROD"].id,
                },
                {
                    "target_type": "application",
                    "target_id": apps["inventory-svc"].id,
                    "environment_id": envs["PROD"].id,
                },
            ],
        },
        actor_id=publisher.id,
    )

    # Approved window only (not yet confirmed)
    event_service.create_event(
        db,
        data={
            "kind": "planned_maintenance",
            "title": "[DEMO] Inventory UAT schema migration (approved window)",
            "description": "Approved change window pending confirmation.",
            "expected_impact": "UAT unavailable",
            "approval_state": "approved_window",
            "starts_at": now + timedelta(days=5),
            "ends_at": now + timedelta(days=5, hours=3),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": apps["inventory-svc"].id,
                    "environment_id": envs["UAT"].id,
                }
            ],
        },
        actor_id=publisher.id,
    )

    # Recent completed
    completed = event_service.create_event(
        db,
        data={
            "kind": "planned_maintenance",
            "title": "[DEMO] Inventory INT cache flush",
            "description": "Completed cache cluster maintenance.",
            "expected_impact": "None after warm-up",
            "approval_state": "confirmed_scheduled",
            "starts_at": now - timedelta(days=3, hours=2),
            "ends_at": now - timedelta(days=3),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": apps["inventory-svc"].id,
                    "environment_id": envs["INT"].id,
                }
            ],
        },
        actor_id=publisher.id,
    )
    event_service.transition_event(
        db, completed, target_status=EventStatus.in_progress, actor_id=publisher.id
    )
    completed = event_service.get_event(db, completed.id)
    event_service.transition_event(
        db, completed, target_status=EventStatus.completed, actor_id=publisher.id, note="Verified OK"
    )

    # Manual outage
    event_service.create_event(
        db,
        data={
            "kind": "manual_outage",
            "title": "[DEMO] HR Portal login failures (manual outage)",
            "description": "Users unable to authenticate; investigating IdP.",
            "expected_impact": "Login unavailable",
            "approval_state": "confirmed_scheduled",
            "starts_at": now - timedelta(minutes=45),
            "ends_at": now + timedelta(hours=3),
            "timezone": "America/Chicago",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": apps["hr-portal"].id,
                    "environment_id": envs["PROD"].id,
                }
            ],
        },
        actor_id=publisher.id,
    )

    # Recurring weekly maintenance (M3b) — Sundays 02:00–04:00 America/Chicago
    # Demonstrates series + one cancelled occurrence + overlapping window with one-shot outages.
    from zoneinfo import ZoneInfo

    chi = ZoneInfo("America/Chicago")
    # Next Sunday 02:00 Chicago
    local_now = now.astimezone(chi)
    days_ahead = (6 - local_now.weekday()) % 7  # Sunday=6 in weekday()
    if days_ahead == 0 and local_now.hour >= 2:
        days_ahead = 7
    next_sun = (local_now + timedelta(days=days_ahead)).replace(
        hour=2, minute=0, second=0, microsecond=0
    )
    recur_start = next_sun.astimezone(timezone.utc)
    recur_end = (next_sun + timedelta(hours=2)).astimezone(timezone.utc)
    until_local = next_sun + timedelta(weeks=12)
    recurring = event_service.create_event(
        db,
        data={
            "kind": "planned_maintenance",
            "title": "[DEMO] Weekly Payments batch window",
            "description": "Recurring Sunday maintenance for Payments Gateway PROD.",
            "expected_impact": "Batch APIs degraded ~2h",
            "approval_state": "confirmed_scheduled",
            "starts_at": recur_start,
            "ends_at": recur_end,
            "timezone": "America/Chicago",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": apps["payments-gateway"].id,
                    "environment_id": envs["PROD"].id,
                }
            ],
            "recurrence": {
                "freq": "WEEKLY",
                "interval": 1,
                "byweekday": ["SU"],
                "until": until_local.astimezone(timezone.utc).isoformat(),
            },
        },
        actor_id=publisher.id,
    )
    # Demo: two occurrences of the same series in different lifecycle states
    from maintenancehub_api.domain import occurrences as occurrence_service
    from maintenancehub_api.domain import recurrence as recurrence_service

    occs = recurrence_service.expand_event_occurrences(
        recurring,
        range_start=recur_start - timedelta(seconds=1),
        range_end=recur_start + timedelta(days=28),
    )
    if len(occs) >= 1:
        # First upcoming occurrence: mark in progress (human-published executing)
        occurrence_service.transition_occurrence(
            db,
            recurring,
            original_starts_at=occs[0].original_starts_at,
            target_status=EventStatus.in_progress,
            actor_id=publisher.id,
            note="[DEMO] Occurrence started",
        )
        recurring = event_service.get_event(db, recurring.id)
    if len(occs) >= 2:
        # Second: leave scheduled but cancel the third as a skip if present
        pass
    if len(occs) >= 3:
        occurrence_service.cancel_occurrence(
            db,
            recurring,
            original_starts_at=occs[2].original_starts_at,
            actor_id=publisher.id,
            note="[DEMO] Skipped occurrence",
        )
        recurring = event_service.get_event(db, recurring.id)
    if len(occs) >= 2:
        # Second occurrence stays scheduled — contrast with first (in_progress)
        occurrence_service.patch_occurrence(
            db,
            recurring,
            original_starts_at=occs[1].original_starts_at,
            actor_id=publisher.id,
            description="[DEMO] Still scheduled — independent of sibling in progress",
        )

    # Approved-window recurring series (not confirmed — reminders should not fire)
    event_service.create_event(
        db,
        data={
            "kind": "planned_maintenance",
            "title": "[DEMO] Monthly Inventory DR drill (approved window)",
            "description": "Recurring approved window — not yet confirmed for communication.",
            "expected_impact": "DR environment only",
            "approval_state": "approved_window",
            "starts_at": (now + timedelta(days=10)).replace(minute=0, second=0, microsecond=0),
            "ends_at": (now + timedelta(days=10, hours=3)),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "application",
                    "target_id": apps["inventory-svc"].id,
                    "environment_id": envs["PROD"].id,
                }
            ],
            "recurrence": {
                "freq": "MONTHLY",
                "interval": 1,
                "bymonthday": (now + timedelta(days=10)).day,
                "count": 6,
            },
        },
        actor_id=publisher.id,
    )

    _seed_m14_oracle_impact_demo(db, apps=apps, envs=envs, publisher=publisher)
    _seed_m15_admin_demo(db)


def _seed_m15_admin_demo(db: Session) -> None:
    """Directory group maps + callouts for the Administration workspace demos."""
    for directory_group, role in (
        ("mh-viewers", RoleName.viewer),
        ("mh-publishers", RoleName.publisher),
        ("mh-admins", RoleName.platform_administrator),
    ):
        existing = (
            db.query(GroupRoleMapping)
            .filter(
                GroupRoleMapping.directory_group == directory_group,
                GroupRoleMapping.role == role,
                GroupRoleMapping.application_id.is_(None),
            )
            .first()
        )
        if not existing:
            db.add(
                GroupRoleMapping(
                    directory_group=directory_group,
                    role=role,
                    application_id=None,
                )
            )
    db.commit()


def _seed_m14_oracle_impact_demo(
    db: Session,
    *,
    apps: dict[str, Application],
    envs: dict[str, Environment],
    publisher: User,
) -> None:
    """Shared Oracle NON-PROD → Claims INT / Billing DEV / Member API QA + transitive Portal BFF."""
    oracle = (
        db.query(InfraComponent).filter(InfraComponent.key == "oracle-shared-nonprod").first()
    )
    if not oracle:
        oracle = InfraComponent(
            key="oracle-shared-nonprod",
            name="[DEMO] Oracle Database (NON-PROD)",
            kind="database",
            description="Shared Oracle instance for non-production workloads",
        )
        db.add(oracle)
        db.flush()

    # External CI links (CMDB-ish) for freshness demo
    for app_key, ext_id in (
        ("claims", "ci-claims"),
        ("billing", "ci-billing"),
        ("member-api", "ci-member-api"),
        ("portal-bff", "ci-portal-bff"),
    ):
        if app_key not in apps:
            continue
        exists = (
            db.query(ExternalCiLink)
            .filter(
                ExternalCiLink.subject_type == "application",
                ExternalCiLink.subject_id == apps[app_key].id,
                ExternalCiLink.source_system == "servicenow",
            )
            .first()
        )
        if not exists:
            db.add(
                ExternalCiLink(
                    subject_type="application",
                    subject_id=apps[app_key].id,
                    source_system="servicenow",
                    external_id=ext_id,
                    display_name=apps[app_key].name,
                )
            )

    def _edge(frm_app: str, frm_env: str | None, to_type: str, to_id: str, to_env: str | None, origin: str):
        if frm_app not in apps:
            return
        q = db.query(Dependency).filter(
            Dependency.from_type == "application",
            Dependency.from_id == apps[frm_app].id,
            Dependency.to_type == to_type,
            Dependency.to_id == to_id,
            Dependency.dependency_kind == "depends_on",
        )
        if frm_env:
            q = q.filter(Dependency.from_environment_id == envs[frm_env].id)
        else:
            q = q.filter(Dependency.from_environment_id.is_(None))
        if to_env:
            q = q.filter(Dependency.to_environment_id == envs[to_env].id)
        else:
            q = q.filter(Dependency.to_environment_id.is_(None))
        if q.first():
            return
        db.add(
            Dependency(
                from_type="application",
                from_id=apps[frm_app].id,
                to_type=to_type,
                to_id=to_id,
                from_environment_id=envs[frm_env].id if frm_env else None,
                to_environment_id=envs[to_env].id if to_env else None,
                dependency_kind="depends_on",
                origin=origin,
            )
        )

    # Consumers → Oracle NON-PROD
    _edge("claims", "INT", "infra_component", oracle.id, "NON-PROD", DependencyOrigin.import_.value)
    _edge("billing", "DEV", "infra_component", oracle.id, "NON-PROD", DependencyOrigin.import_.value)
    _edge("member-api", "QA", "infra_component", oracle.id, "NON-PROD", DependencyOrigin.manual.value)
    # Transitive: Portal BFF QA → Member API QA
    _edge("portal-bff", "QA", "application", apps["member-api"].id, "QA", DependencyOrigin.manual.value)
    db.commit()

    # Subscriptions for reach preview (unique destinations)
    for email, app_key, env_key in (
        ("claims-int-watch@demo.example.com", "claims", "INT"),
        ("billing-dev-watch@demo.example.com", "billing", "DEV"),
        ("member-qa-watch@demo.example.com", "member-api", "QA"),
    ):
        if app_key not in apps:
            continue
        existing = (
            db.query(Subscription).filter(Subscription.destination == email).first()
        )
        if existing:
            continue
        sub = Subscription(
            user_id=publisher.id,
            destination_type="email_address",
            destination=email,
            is_active=True,
        )
        db.add(sub)
        db.flush()
        db.add(
            SubscriptionTarget(
                subscription_id=sub.id,
                target_type="app_environment",
                target_id=f"{apps[app_key].id}:{envs[env_key].id}",
            )
        )
        db.add(ReminderOffset(subscription_id=sub.id, offset_minutes=-60))
    db.commit()

    # Recurring Oracle maintenance — series default Oracle NON-PROD; one occ different impacts
    from maintenancehub_api.models import MaintenanceEvent

    title = "[DEMO] Oracle NON-PROD patch window (impact analysis)"
    if db.query(MaintenanceEvent).filter(MaintenanceEvent.title == title).first():
        return

    now = datetime.now(timezone.utc)
    starts = (now + timedelta(days=5)).replace(hour=2, minute=0, second=0, microsecond=0)
    series = event_service.create_event(
        db,
        data={
            "kind": "planned_maintenance",
            "title": title,
            "description": (
                "M14 demo: shared Oracle NON-PROD. Preview suggests Claims INT, Billing DEV, "
                "Member API QA, and transitive Portal BFF QA."
            ),
            "expected_impact": "DB brief unavailability in NON-PROD",
            "approval_state": "approved_window",
            "starts_at": starts,
            "ends_at": starts + timedelta(hours=2),
            "timezone": "UTC",
            "impacts": [
                {
                    "target_type": "infra_component",
                    "target_id": oracle.id,
                    "environment_id": envs["NON-PROD"].id,
                }
            ],
            "recurrence": {"freq": "WEEKLY", "interval": 1, "count": 4},
        },
        actor_id=publisher.id,
    )
    from maintenancehub_api.domain import occurrences as occurrence_service
    from maintenancehub_api.domain import recurrence as recurrence_service

    occs = recurrence_service.expand_event_occurrences(
        series,
        range_start=starts - timedelta(seconds=1),
        range_end=starts + timedelta(days=28),
    )
    if len(occs) >= 2:
        # Second occurrence: override to Claims INT only (differs from series default)
        occurrence_service.patch_occurrence(
            db,
            series,
            original_starts_at=occs[1].original_starts_at,
            actor_id=publisher.id,
            description="[DEMO] Occurrence-specific impacts (Claims INT only)",
            impacts=[
                {
                    "target_type": "application",
                    "target_id": apps["claims"].id,
                    "environment_id": envs["INT"].id,
                }
            ],
        )
    # Overlapping Claims maintenance for conflict demo
    overlap_title = "[DEMO] Claims INT batch (overlaps Oracle window)"
    if not db.query(MaintenanceEvent).filter(MaintenanceEvent.title == overlap_title).first():
        event_service.create_event(
            db,
            data={
                "kind": "planned_maintenance",
                "title": overlap_title,
                "description": "Overlaps Oracle NON-PROD window — advisory conflict in impact preview",
                "approval_state": "confirmed_scheduled",
                "starts_at": starts + timedelta(minutes=30),
                "ends_at": starts + timedelta(hours=3),
                "timezone": "UTC",
                "impacts": [
                    {
                        "target_type": "application",
                        "target_id": apps["claims"].id,
                        "environment_id": envs["INT"].id,
                    }
                ],
            },
            actor_id=publisher.id,
        )
