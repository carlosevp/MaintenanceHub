"""Maintenance impact dependency traversal (M14).

``Dependency`` edges mean consumer (from) depends on provider (to).
Maintenance on a provider finds potentially affected consumers by walking
reverse edges. No confidence percentages — evidence classes only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from maintenancehub_api.domain.impacts import ImpactRef
from maintenancehub_api.models import (
    Application,
    Dependency,
    Environment,
    ExternalCiLink,
    InfraComponent,
    Service,
)
from maintenancehub_api.schemas.common import ensure_utc

DEFAULT_MAX_DEPTH = 5
# Imported/CMDB edges older than this emit a freshness warning (advisory).
STALE_AFTER_DAYS = 90


@dataclass
class PathHop:
    via_dependency_id: str
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    from_environment_id: str | None
    to_environment_id: str | None
    origin: str
    dependency_kind: str


@dataclass
class SuggestedImpact:
    target_type: str
    target_id: str
    environment_id: str | None
    classification: str  # direct | downstream_candidate
    display_name: str
    paths: list[list[PathHop]] = field(default_factory=list)
    origins: set[str] = field(default_factory=set)
    dependency_kinds: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str, str | None]:
        return (self.target_type, self.target_id, self.environment_id)


@dataclass
class AnalysisWarning:
    code: str
    message: str
    subject_type: str | None = None
    subject_id: str | None = None


@dataclass
class DependencyAnalysisResult:
    direct: list[SuggestedImpact]
    downstream: list[SuggestedImpact]
    warnings: list[AnalysisWarning]
    max_depth: int
    analyzed_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _label(db: Session, target_type: str, target_id: str) -> str:
    if target_type == "application":
        row = db.get(Application, target_id)
        return row.name if row else target_id
    if target_type == "service":
        row = db.get(Service, target_id)
        return row.name if row else target_id
    if target_type == "infra_component":
        row = db.get(InfraComponent, target_id)
        return row.name if row else target_id
    return target_id


def _env_key(db: Session, env_id: str | None) -> str | None:
    if not env_id:
        return None
    row = db.get(Environment, env_id)
    return row.key if row else env_id


def _node_key(t: str, i: str, e: str | None) -> tuple[str, str, str | None]:
    return (t, i, e)


def _freshness_warning(dep: Dependency, now: datetime) -> str | None:
    if dep.origin == "manual":
        return None
    updated = ensure_utc(dep.updated_at) if dep.updated_at else None
    if updated is None:
        return "Imported dependency has no last-updated timestamp — treat as potentially stale"
    age = now - updated
    if age > timedelta(days=STALE_AFTER_DAYS):
        return (
            f"Imported dependency last updated {updated.date().isoformat()} "
            f"(>{STALE_AFTER_DAYS}d) — verify before relying on this edge"
        )
    return None


def analyze_downstream_impacts(
    db: Session,
    *,
    seeds: list[ImpactRef],
    max_depth: int = DEFAULT_MAX_DEPTH,
    now: datetime | None = None,
) -> DependencyAnalysisResult:
    """BFS reverse traversal from seed providers to dependent consumers.

    Absent edges never imply 'no dependencies exist' — callers should surface
    a data-unavailable warning when the seed graph is empty of outbound edges.
    """
    now = ensure_utc(now or _now())
    max_depth = max(0, min(int(max_depth), 20))

    all_deps = db.query(Dependency).all()
    # Index: provider (to) → list of edges where consumers (from) depend on provider
    by_provider: dict[tuple[str, str], list[Dependency]] = {}
    for dep in all_deps:
        by_provider.setdefault((dep.to_type, dep.to_id), []).append(dep)

    warnings: list[AnalysisWarning] = []
    direct_map: dict[tuple[str, str, str | None], SuggestedImpact] = {}
    down_map: dict[tuple[str, str, str | None], SuggestedImpact] = {}

    for seed in seeds:
        key = _node_key(seed.target_type, seed.target_id, seed.environment_id)
        direct_map[key] = SuggestedImpact(
            target_type=seed.target_type,
            target_id=seed.target_id,
            environment_id=seed.environment_id,
            classification="direct",
            display_name=_label(db, seed.target_type, seed.target_id),
            origins=set(),
            paths=[],
        )
        # CI mapping freshness for seed applications
        if seed.is_application:
            links = (
                db.query(ExternalCiLink)
                .filter(
                    ExternalCiLink.subject_type == "application",
                    ExternalCiLink.subject_id == seed.target_id,
                )
                .all()
            )
            if not links:
                warnings.append(
                    AnalysisWarning(
                        code="no_external_ci_link",
                        message=(
                            f"No ExternalCiLink for {_label(db, 'application', seed.target_id)} "
                            "— CMDB-derived edges may be incomplete (absent ≠ none)"
                        ),
                        subject_type="application",
                        subject_id=seed.target_id,
                    )
                )
            for link in links:
                if link.updated_at and ensure_utc(link.updated_at) < now - timedelta(
                    days=STALE_AFTER_DAYS
                ):
                    warnings.append(
                        AnalysisWarning(
                            code="stale_ci_link",
                            message=(
                                f"ExternalCiLink {link.source_system}:{link.external_id} "
                                f"last updated {ensure_utc(link.updated_at).date().isoformat()}"
                            ),
                            subject_type="application",
                            subject_id=seed.target_id,
                        )
                    )

    # Queue: (type, id, env_id, depth, path_so_far)
    queue: list[tuple[str, str, str | None, int, list[PathHop]]] = [
        (s.target_type, s.target_id, s.environment_id, 0, []) for s in seeds
    ]
    visited_provider_hops: set[tuple[str, str, str | None, str]] = set()

    while queue:
        p_type, p_id, p_env, depth, path = queue.pop(0)
        if depth >= max_depth:
            continue
        edges = by_provider.get((p_type, p_id), [])
        if depth == 0 and not edges and (p_type, p_id, p_env) in {
            (s.target_type, s.target_id, s.environment_id) for s in seeds
        }:
            warnings.append(
                AnalysisWarning(
                    code="no_known_dependents",
                    message=(
                        f"No recorded dependents of {_label(db, p_type, p_id)} "
                        f"({_env_key(db, p_env) or 'any-env'}). "
                        "Absent dependency data is not proof that none exist."
                    ),
                    subject_type=p_type,
                    subject_id=p_id,
                )
            )
        for dep in edges:
            # Environment filter: if edge pins provider env, require match when seed/env known
            if dep.to_environment_id and p_env and dep.to_environment_id != p_env:
                continue
            consumer_env = dep.from_environment_id
            hop_key = (dep.from_type, dep.from_id, consumer_env, dep.id)
            if hop_key in visited_provider_hops:
                # Still record alternate path on existing suggestion
                pass
            visited_provider_hops.add(hop_key)

            hop = PathHop(
                via_dependency_id=dep.id,
                from_type=dep.from_type,
                from_id=dep.from_id,
                to_type=dep.to_type,
                to_id=dep.to_id,
                from_environment_id=dep.from_environment_id,
                to_environment_id=dep.to_environment_id,
                origin=dep.origin,
                dependency_kind=dep.dependency_kind,
            )
            new_path = path + [hop]
            ckey = _node_key(dep.from_type, dep.from_id, consumer_env)

            # Cycle: consumer already on this path, or reverse edge returns to a seed
            in_path = any(
                h.from_type == dep.from_type and h.from_id == dep.from_id for h in path
            )
            seed_revisit = any(
                (s.target_type, s.target_id) == (dep.from_type, dep.from_id) for s in seeds
            )
            if in_path or seed_revisit:
                warnings.append(
                    AnalysisWarning(
                        code="cycle_detected",
                        message=(
                            f"Cycle involving {_label(db, dep.from_type, dep.from_id)}; "
                            "traversal stopped for this path"
                        ),
                        subject_type=dep.from_type,
                        subject_id=dep.from_id,
                    )
                )
                continue

            # Skip if this is a seed direct target (keep as direct, don't reclassify)
            if ckey in direct_map:
                continue

            sug = down_map.get(ckey)
            if sug is None:
                sug = SuggestedImpact(
                    target_type=dep.from_type,
                    target_id=dep.from_id,
                    environment_id=consumer_env,
                    classification="downstream_candidate",
                    display_name=_label(db, dep.from_type, dep.from_id),
                )
                down_map[ckey] = sug
            sug.paths.append(new_path)
            sug.origins.add(dep.origin)
            sug.dependency_kinds.add(dep.dependency_kind)
            fw = _freshness_warning(dep, now)
            if fw and fw not in sug.warnings:
                sug.warnings.append(fw)

            queue.append(
                (dep.from_type, dep.from_id, consumer_env, depth + 1, new_path)
            )

    # Dedupe paths within each suggestion (identical hop id sequences)
    for sug in down_map.values():
        seen_sig: set[tuple[str, ...]] = set()
        unique_paths: list[list[PathHop]] = []
        for p in sug.paths:
            sig = tuple(h.via_dependency_id for h in p)
            if sig in seen_sig:
                continue
            seen_sig.add(sig)
            unique_paths.append(p)
        sug.paths = unique_paths

    return DependencyAnalysisResult(
        direct=list(direct_map.values()),
        downstream=list(down_map.values()),
        warnings=_dedupe_warnings(warnings),
        max_depth=max_depth,
        analyzed_at=now,
    )


def _dedupe_warnings(warnings: list[AnalysisWarning]) -> list[AnalysisWarning]:
    seen: set[tuple[str, str | None, str | None, str]] = set()
    out: list[AnalysisWarning] = []
    for w in warnings:
        key = (w.code, w.subject_type, w.subject_id, w.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


def suggested_to_dict(sug: SuggestedImpact, db: Session) -> dict[str, Any]:
    return {
        "target_type": sug.target_type,
        "target_id": sug.target_id,
        "environment_id": sug.environment_id,
        "environment_key": _env_key(db, sug.environment_id),
        "display_name": sug.display_name,
        "classification": sug.classification,
        "origins": sorted(sug.origins),
        "dependency_kinds": sorted(sug.dependency_kinds),
        "warnings": list(sug.warnings),
        "paths": [
            [
                {
                    "dependency_id": h.via_dependency_id,
                    "consumer_type": h.from_type,
                    "consumer_id": h.from_id,
                    "consumer_name": _label(db, h.from_type, h.from_id),
                    "consumer_environment_id": h.from_environment_id,
                    "consumer_environment_key": _env_key(db, h.from_environment_id),
                    "provider_type": h.to_type,
                    "provider_id": h.to_id,
                    "provider_name": _label(db, h.to_type, h.to_id),
                    "provider_environment_id": h.to_environment_id,
                    "provider_environment_key": _env_key(db, h.to_environment_id),
                    "origin": h.origin,
                    "dependency_kind": h.dependency_kind,
                }
                for h in path
            ]
            for path in sug.paths
        ],
    }
