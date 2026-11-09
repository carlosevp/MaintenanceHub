from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user, require_roles
from maintenancehub_api.models import (
    AppEnvironment,
    Application,
    CatalogStatus,
    Dependency,
    Environment,
    ExternalCiLink,
    InfraComponent,
    Ownership,
    OwnerType,
    SubjectType,
    SupportGroup,
    Tag,
    Tagging,
)
from maintenancehub_api.schemas.catalog import (
    AppEnvironmentIn,
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    DependencyCreate,
    DependencyOut,
    EnvironmentCreate,
    EnvironmentOut,
    EnvironmentUpdate,
    ExternalCiLinkIn,
    ExternalCiLinkOut,
    InfraComponentOut,
    OwnershipIn,
    OwnershipOut,
    SupportGroupCreate,
    SupportGroupOut,
    TagCreate,
    TagOut,
)

router = APIRouter(tags=["catalog"])


def _app_out(app: Application) -> ApplicationOut:
    return ApplicationOut.model_validate(app)


@router.get("/environments", response_model=list[EnvironmentOut])
def list_environments(
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
    include_inactive: bool = Query(False),
) -> list[Environment]:
    query = db.query(Environment)
    if not include_inactive:
        query = query.filter(Environment.is_active.is_(True))
    return query.order_by(Environment.sort_order, Environment.key).all()


@router.post("/environments", response_model=EnvironmentOut, status_code=201)
def create_environment(
    body: EnvironmentCreate,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles("platform_administrator", "publisher")),
) -> Environment:
    key = body.key.strip().upper()
    if db.query(Environment).filter(Environment.key == key).first():
        raise HTTPException(status_code=409, detail="Environment code already exists")
    env = Environment(
        key=key,
        name=body.name.strip(),
        description=body.description,
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    db.add(env)
    db.commit()
    db.refresh(env)
    return env


@router.patch("/environments/{env_id}", response_model=EnvironmentOut)
def update_environment(
    env_id: str,
    body: EnvironmentUpdate,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles("platform_administrator")),
) -> Environment:
    env = db.get(Environment, env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        env.name = data["name"].strip()
    if "description" in data:
        env.description = data["description"]
    if "sort_order" in data and data["sort_order"] is not None:
        env.sort_order = data["sort_order"]
    if "is_active" in data and data["is_active"] is not None:
        env.is_active = data["is_active"]
    db.commit()
    db.refresh(env)
    return env


@router.post("/environments/{env_id}/deactivate", response_model=EnvironmentOut)
def deactivate_environment(
    env_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles("platform_administrator")),
) -> Environment:
    """Prefer deactivate over delete so historical impacts keep stable identities."""
    env = db.get(Environment, env_id)
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    env.is_active = False
    db.commit()
    db.refresh(env)
    return env


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(
    q: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> list[Application]:
    query = db.query(Application).options(
        joinedload(Application.environments).joinedload(AppEnvironment.environment)
    )
    if q:
        like = f"%{q}%"
        query = query.filter((Application.name.ilike(like)) | (Application.key.ilike(like)))
    if status_filter:
        query = query.filter(Application.status == CatalogStatus(status_filter))
    return query.order_by(Application.name).offset(offset).limit(limit).all()


@router.post("/applications", response_model=ApplicationOut, status_code=201)
def create_application(
    body: ApplicationCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> Application:
    if db.query(Application).filter(Application.key == body.key).first():
        raise HTTPException(status_code=409, detail="Application key already exists")
    app = Application(key=body.key, name=body.name, description=body.description)
    db.add(app)
    db.flush()
    for env_in in body.environments:
        env = db.get(Environment, env_in.environment_id)
        if not env:
            raise HTTPException(status_code=400, detail=f"Unknown environment {env_in.environment_id}")
        db.add(
            AppEnvironment(
                application_id=app.id,
                environment_id=env.id,
                display_name=env_in.display_name,
            )
        )
    # Creator receives an application-scoped grant (enforced on later writes).
    from maintenancehub_api.domain.authz import grant_user_on_application

    if not user.is_admin:
        role = "application_owner" if user.has_role("application_owner") else "publisher"
        grant_user_on_application(
            db, user_id=user.id, application_id=app.id, role=role
        )
    db.commit()
    return (
        db.query(Application)
        .options(joinedload(Application.environments).joinedload(AppEnvironment.environment))
        .filter(Application.id == app.id)
        .one()
    )


@router.get("/applications/{app_id}", response_model=ApplicationOut)
def get_application(
    app_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> Application:
    app = (
        db.query(Application)
        .options(joinedload(Application.environments).joinedload(AppEnvironment.environment))
        .filter(Application.id == app_id)
        .first()
    )
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.patch("/applications/{app_id}", response_model=ApplicationOut)
def update_application(
    app_id: str,
    body: ApplicationUpdate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> Application:
    from maintenancehub_api.domain.authz import ensure_app_grants

    ensure_app_grants(db, user, [app_id], action="update application")
    app = db.get(Application, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if body.name is not None:
        app.name = body.name
    if body.description is not None:
        app.description = body.description
    if body.status is not None:
        app.status = CatalogStatus(body.status)
    db.commit()
    return (
        db.query(Application)
        .options(joinedload(Application.environments).joinedload(AppEnvironment.environment))
        .filter(Application.id == app_id)
        .one()
    )


@router.delete("/applications/{app_id}", status_code=204)
def delete_application(
    app_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles("platform_administrator")),
) -> None:
    app = db.get(Application, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    db.delete(app)
    db.commit()


@router.put("/applications/{app_id}/environments", response_model=list[AppEnvironmentIn])
def put_app_environments(
    app_id: str,
    body: list[AppEnvironmentIn],
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> list[AppEnvironmentIn]:
    app = db.get(Application, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    db.query(AppEnvironment).filter(AppEnvironment.application_id == app_id).delete()
    for env_in in body:
        if not db.get(Environment, env_in.environment_id):
            raise HTTPException(status_code=400, detail=f"Unknown environment {env_in.environment_id}")
        db.add(
            AppEnvironment(
                application_id=app_id,
                environment_id=env_in.environment_id,
                display_name=env_in.display_name,
            )
        )
    db.commit()
    return body


@router.get("/applications/{app_id}/owners", response_model=list[OwnershipOut])
def list_owners(
    app_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> list[Ownership]:
    return (
        db.query(Ownership)
        .filter(
            Ownership.subject_type == SubjectType.application,
            Ownership.subject_id == app_id,
        )
        .all()
    )


@router.put("/applications/{app_id}/owners", response_model=list[OwnershipOut])
def put_owners(
    app_id: str,
    body: list[OwnershipIn],
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles("application_owner", "platform_administrator")),
) -> list[Ownership]:
    if not db.get(Application, app_id):
        raise HTTPException(status_code=404, detail="Application not found")
    db.query(Ownership).filter(
        Ownership.subject_type == SubjectType.application,
        Ownership.subject_id == app_id,
    ).delete()
    rows: list[Ownership] = []
    for item in body:
        row = Ownership(
            subject_type=SubjectType.application,
            subject_id=app_id,
            owner_type=OwnerType(item.owner_type),
            owner_id=item.owner_id,
        )
        db.add(row)
        rows.append(row)
    db.commit()
    return list_owners(app_id, db, _)  # type: ignore[arg-type]


@router.get("/applications/{app_id}/dependencies", response_model=list[DependencyOut])
def list_dependencies(
    app_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> list[Dependency]:
    return (
        db.query(Dependency)
        .filter(Dependency.from_type == "application", Dependency.from_id == app_id)
        .all()
    )


@router.post(
    "/applications/{app_id}/dependencies",
    response_model=DependencyOut,
    status_code=201,
)
def create_dependency(
    app_id: str,
    body: DependencyCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> Dependency:
    if not db.get(Application, app_id):
        raise HTTPException(status_code=404, detail="Application not found")
    from maintenancehub_api.domain.authz import ensure_app_grants

    # Cross-app: publishers need a grant on the consumer application.
    ensure_app_grants(db, user, [app_id], action="create dependency for")
    if body.to_type == "application" and body.to_id == app_id:
        raise HTTPException(
            status_code=400,
            detail="Self-reference rejected: Consumer cannot depend on itself",
        )
    existing = (
        db.query(Dependency)
        .filter(
            Dependency.from_type == "application",
            Dependency.from_id == app_id,
            Dependency.to_type == body.to_type,
            Dependency.to_id == body.to_id,
            Dependency.dependency_kind == body.dependency_kind,
            Dependency.from_environment_id == body.from_environment_id,
            Dependency.to_environment_id == body.to_environment_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Duplicate dependency relationship")
    dep = Dependency(
        from_type="application",
        from_id=app_id,
        to_type=body.to_type,
        to_id=body.to_id,
        dependency_kind=body.dependency_kind,
        origin="manual",
        from_environment_id=body.from_environment_id,
        to_environment_id=body.to_environment_id,
    )
    db.add(dep)
    db.commit()
    db.refresh(dep)
    return dep


@router.get("/applications/{app_id}/external-ci-links", response_model=list[ExternalCiLinkOut])
def list_ci_links(
    app_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> list[ExternalCiLink]:
    return (
        db.query(ExternalCiLink)
        .filter(ExternalCiLink.subject_type == "application", ExternalCiLink.subject_id == app_id)
        .all()
    )


@router.put("/applications/{app_id}/external-ci-links", response_model=list[ExternalCiLinkOut])
def put_ci_links(
    app_id: str,
    body: list[ExternalCiLinkIn],
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles("publisher", "application_owner", "platform_administrator")),
) -> list[ExternalCiLink]:
    if not db.get(Application, app_id):
        raise HTTPException(status_code=404, detail="Application not found")
    db.query(ExternalCiLink).filter(
        ExternalCiLink.subject_type == "application",
        ExternalCiLink.subject_id == app_id,
    ).delete()
    for item in body:
        db.add(
            ExternalCiLink(
                subject_type="application",
                subject_id=app_id,
                source_system=item.source_system,
                external_id=item.external_id,
                display_name=item.display_name,
            )
        )
    db.commit()
    return list_ci_links(app_id, db, _)  # type: ignore[arg-type]


@router.get("/infra-components", response_model=list[InfraComponentOut])
def list_infra_components(
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
    q: str | None = Query(None),
) -> list[InfraComponent]:
    query = db.query(InfraComponent)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (InfraComponent.key.ilike(like)) | (InfraComponent.name.ilike(like))
        )
    return query.order_by(InfraComponent.name).all()


@router.get("/tags", response_model=list[TagOut])
def list_tags(
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> list[Tag]:
    return db.query(Tag).order_by(Tag.name).all()


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(
    body: TagCreate,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles("publisher", "platform_administrator")),
) -> Tag:
    tag = Tag(key=body.key, name=body.name)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.post("/taggings", status_code=201)
def create_tagging(
    tag_id: str,
    subject_type: str,
    subject_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles("publisher", "platform_administrator")),
) -> dict[str, str]:
    if not db.get(Tag, tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")
    db.add(Tagging(tag_id=tag_id, subject_type=subject_type, subject_id=subject_id))
    db.commit()
    return {"status": "created"}


@router.get("/support-groups", response_model=list[SupportGroupOut])
def list_support_groups(
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
) -> list[SupportGroup]:
    return db.query(SupportGroup).order_by(SupportGroup.name).all()


@router.post("/support-groups", response_model=SupportGroupOut, status_code=201)
def create_support_group(
    body: SupportGroupCreate,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles("platform_administrator")),
) -> SupportGroup:
    group = SupportGroup(key=body.key, name=body.name, directory_group=body.directory_group)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group
