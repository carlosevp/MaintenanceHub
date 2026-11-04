"""Labeled demo data for local_dev. Safe to re-run (idempotent on keys/emails)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from maintenancehub_api.auth.security import hash_password
from maintenancehub_api.domain import events as event_service
from maintenancehub_api.models import (
    AppEnvironment,
    Application,
    EventStatus,
    Environment,
    Role,
    RoleName,
    SupportGroup,
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
    publisher = users["publisher@demo.example.com"]

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
