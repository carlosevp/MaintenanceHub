"""CMDB CSV import — preview / commit with external-id idempotency (M10)."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from maintenancehub_api.models import (
    Application,
    CatalogStatus,
    CsvImportJob,
    Dependency,
    ExternalCiLink,
)

logger = logging.getLogger("maintenancehub.csv_import")

DEFAULT_CI_MAP = {
    "external_id": "sys_id",
    "key": "name",
    "name": "short_description",
    "description": "description",
}

DEFAULT_REL_MAP = {
    "from_external_id": "parent_sys_id",
    "to_external_id": "child_sys_id",
    "dependency_kind": "type",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slug(value: str) -> str:
    raw = "".join(c.lower() if c.isalnum() else "-" for c in value.strip())
    while "--" in raw:
        raw = raw.replace("--", "-")
    return raw.strip("-")[:80] or "ci"


def parse_csv(raw: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(raw))
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def create_import_job(
    db: Session,
    *,
    kind: str,
    filename: str,
    raw_csv: str,
    column_map: dict[str, str] | None,
    options: dict[str, Any] | None,
    created_by: str | None,
) -> CsvImportJob:
    if kind not in {"cmdb_ci", "ci_relationships"}:
        raise ValueError("kind must be cmdb_ci or ci_relationships")
    default_map = DEFAULT_CI_MAP if kind == "cmdb_ci" else DEFAULT_REL_MAP
    job = CsvImportJob(
        kind=kind,
        filename=filename,
        status="uploaded",
        column_map=column_map or default_map,
        options=options or {},
        raw_csv=raw_csv,
        created_by=created_by,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def preview_import(db: Session, job: CsvImportJob) -> dict[str, Any]:
    rows = parse_csv(job.raw_csv)
    cmap = job.column_map or {}
    errors: list[dict[str, Any]] = []
    valid = 0
    for i, row in enumerate(rows, start=2):  # header is line 1
        mapped = _apply_map(row, cmap)
        if job.kind == "cmdb_ci":
            if not mapped.get("external_id"):
                errors.append({"line": i, "error": "missing external_id/sys_id", "row": row})
                continue
            if not mapped.get("name") and not mapped.get("key"):
                errors.append({"line": i, "error": "missing name/key", "row": row})
                continue
            valid += 1
        else:
            if not mapped.get("from_external_id") or not mapped.get("to_external_id"):
                errors.append(
                    {"line": i, "error": "missing parent/child external ids", "row": row}
                )
                continue
            valid += 1
    preview = {
        "total_rows": len(rows),
        "valid_rows": valid,
        "error_count": len(errors),
        "errors": errors[:50],
        "column_map": cmap,
        "sample": [_apply_map(r, cmap) for r in rows[:3]],
    }
    job.preview = preview
    job.status = "previewed"
    db.commit()
    return preview


def commit_import(db: Session, job: CsvImportJob) -> dict[str, Any]:
    if job.status not in {"uploaded", "previewed"}:
        raise ValueError(f"Cannot commit job in status {job.status}")
    if not job.preview:
        preview_import(db, job)
        db.refresh(job)

    rows = parse_csv(job.raw_csv)
    cmap = job.column_map or {}
    overwrite_manual = bool((job.options or {}).get("overwrite_manual_dependencies"))
    created = updated = skipped = rel_created = rel_skipped = 0
    errors: list[dict[str, Any]] = []

    if job.kind == "cmdb_ci":
        for i, row in enumerate(rows, start=2):
            mapped = _apply_map(row, cmap)
            ext_id = mapped.get("external_id")
            if not ext_id:
                errors.append({"line": i, "error": "missing external_id"})
                continue
            name = mapped.get("name") or mapped.get("key") or ext_id
            key = _slug(mapped.get("key") or name)
            link = (
                db.query(ExternalCiLink)
                .filter(
                    ExternalCiLink.source_system == "servicenow",
                    ExternalCiLink.external_id == ext_id,
                )
                .first()
            )
            if link and link.subject_type == "application":
                app = db.get(Application, link.subject_id)
                if app:
                    app.name = name
                    if mapped.get("description"):
                        app.description = mapped["description"]
                    link.display_name = name
                    updated += 1
                    continue
            # Find by key or create
            app = db.query(Application).filter(Application.key == key).first()
            if app is None:
                # Ensure unique key
                base = key
                n = 1
                while db.query(Application).filter(Application.key == key).first():
                    key = f"{base}-{n}"
                    n += 1
                app = Application(
                    key=key,
                    name=name,
                    description=mapped.get("description"),
                    status=CatalogStatus.active,
                )
                db.add(app)
                db.flush()
                created += 1
            else:
                app.name = name
                if mapped.get("description"):
                    app.description = mapped["description"]
                updated += 1
            existing_link = (
                db.query(ExternalCiLink)
                .filter(
                    ExternalCiLink.subject_type == "application",
                    ExternalCiLink.subject_id == app.id,
                    ExternalCiLink.source_system == "servicenow",
                )
                .first()
            )
            if existing_link:
                existing_link.external_id = ext_id
                existing_link.display_name = name
            else:
                # Check global unique external_id
                clash = (
                    db.query(ExternalCiLink)
                    .filter(
                        ExternalCiLink.source_system == "servicenow",
                        ExternalCiLink.external_id == ext_id,
                    )
                    .first()
                )
                if clash:
                    skipped += 1
                    errors.append(
                        {
                            "line": i,
                            "error": f"external_id {ext_id} already linked to another subject",
                        }
                    )
                    continue
                db.add(
                    ExternalCiLink(
                        subject_type="application",
                        subject_id=app.id,
                        source_system="servicenow",
                        external_id=ext_id,
                        display_name=name,
                    )
                )
    else:
        # relationships
        for i, row in enumerate(rows, start=2):
            mapped = _apply_map(row, cmap)
            from_ext = mapped.get("from_external_id")
            to_ext = mapped.get("to_external_id")
            kind = mapped.get("dependency_kind") or "depends_on"
            if not from_ext or not to_ext:
                errors.append({"line": i, "error": "missing ids"})
                continue
            from_link = (
                db.query(ExternalCiLink)
                .filter(
                    ExternalCiLink.source_system == "servicenow",
                    ExternalCiLink.external_id == from_ext,
                )
                .first()
            )
            to_link = (
                db.query(ExternalCiLink)
                .filter(
                    ExternalCiLink.source_system == "servicenow",
                    ExternalCiLink.external_id == to_ext,
                )
                .first()
            )
            if not from_link or not to_link:
                errors.append({"line": i, "error": "CI not found for relationship endpoints"})
                continue
            existing = (
                db.query(Dependency)
                .filter(
                    Dependency.from_type == from_link.subject_type,
                    Dependency.from_id == from_link.subject_id,
                    Dependency.to_type == to_link.subject_type,
                    Dependency.to_id == to_link.subject_id,
                    Dependency.dependency_kind == kind,
                )
                .first()
            )
            if existing:
                if existing.origin == "manual" and not overwrite_manual:
                    rel_skipped += 1
                    continue
                if existing.origin == "manual" and overwrite_manual:
                    existing.origin = "import"
                rel_skipped += 1
                continue
            db.add(
                Dependency(
                    from_type=from_link.subject_type,
                    from_id=from_link.subject_id,
                    to_type=to_link.subject_type,
                    to_id=to_link.subject_id,
                    dependency_kind=kind,
                    origin="import",
                )
            )
            rel_created += 1

    import_mode = (job.options or {}).get("import_mode", "partial")
    if import_mode not in {"partial", "full"}:
        import_mode = "partial"
    summary = {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "relationships_created": rel_created,
        "relationships_skipped": rel_skipped,
        "errors": errors[:50],
        "overwrite_manual_dependencies": overwrite_manual,
        "import_mode": import_mode,
        # Absences are never deleted — even for import_mode=full in v1.
        "absences_deleted": 0,
        "absence_policy": (
            "never_delete_missing_edges — partial CSV absences are non-destructive; "
            "full-snapshot deletion remains unsupported"
        ),
    }
    job.result_summary = summary
    job.status = "committed"
    job.committed_at = _now()
    db.commit()
    return summary


def _apply_map(row: dict[str, str], cmap: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for logical, csv_col in cmap.items():
        out[logical] = row.get(csv_col, "")
    return out
