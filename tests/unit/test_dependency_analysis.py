"""M14 dependency analysis domain — traversal, cycles, freshness, cross-env."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from maintenancehub_api.domain.dependency_analysis import analyze_downstream_impacts
from maintenancehub_api.domain.impacts import ImpactRef
from maintenancehub_api.models import (
    Application,
    Dependency,
    Environment,
    InfraComponent,
)


def _env(db, key: str) -> Environment:
    row = Environment(key=key, name=key, sort_order=0)
    db.add(row)
    db.flush()
    return row


def _app(db, key: str) -> Application:
    row = Application(key=key, name=key, description=None)
    db.add(row)
    db.flush()
    return row


def _infra(db, key: str) -> InfraComponent:
    row = InfraComponent(key=key, name=key, kind="database")
    db.add(row)
    db.flush()
    return row


def _edge(db, **kwargs) -> Dependency:
    d = Dependency(**kwargs)
    db.add(d)
    db.flush()
    return d


def test_direct_and_transitive_reverse_traversal(db_session):
    db = db_session
    nonprod = _env(db, "NON-PROD")
    qa = _env(db, "QA")
    oracle = _infra(db, "oracle")
    member = _app(db, "member-api")
    portal = _app(db, "portal-bff")
    _edge(
        db,
        from_type="application",
        from_id=member.id,
        to_type="infra_component",
        to_id=oracle.id,
        from_environment_id=qa.id,
        to_environment_id=nonprod.id,
        origin="import",
    )
    _edge(
        db,
        from_type="application",
        from_id=portal.id,
        to_type="application",
        to_id=member.id,
        from_environment_id=qa.id,
        to_environment_id=qa.id,
        origin="manual",
    )
    db.commit()

    result = analyze_downstream_impacts(
        db,
        seeds=[ImpactRef("infra_component", oracle.id, nonprod.id)],
        max_depth=5,
    )
    assert len(result.direct) == 1
    down_ids = {s.target_id for s in result.downstream}
    assert member.id in down_ids
    assert portal.id in down_ids
    portal_sug = next(s for s in result.downstream if s.target_id == portal.id)
    assert portal_sug.classification == "downstream_candidate"
    assert portal_sug.paths and len(portal_sug.paths[0]) == 2


def test_cycle_detection_stops_path(db_session):
    db = db_session
    a = _app(db, "a")
    b = _app(db, "b")
    _edge(
        db,
        from_type="application",
        from_id=a.id,
        to_type="application",
        to_id=b.id,
        origin="manual",
    )
    _edge(
        db,
        from_type="application",
        from_id=b.id,
        to_type="application",
        to_id=a.id,
        origin="manual",
    )
    db.commit()
    result = analyze_downstream_impacts(
        db, seeds=[ImpactRef("application", a.id, None)], max_depth=5
    )
    assert any(w.code == "cycle_detected" for w in result.warnings)


def test_duplicate_paths_deduped(db_session):
    db = db_session
    provider = _app(db, "provider")
    consumer = _app(db, "consumer")
    # Two edges same endpoints different kind — both reverse-walked
    _edge(
        db,
        from_type="application",
        from_id=consumer.id,
        to_type="application",
        to_id=provider.id,
        dependency_kind="depends_on",
        origin="manual",
    )
    _edge(
        db,
        from_type="application",
        from_id=consumer.id,
        to_type="application",
        to_id=provider.id,
        dependency_kind="uses",
        origin="import",
    )
    db.commit()
    result = analyze_downstream_impacts(
        db, seeds=[ImpactRef("application", provider.id, None)]
    )
    sug = result.downstream[0]
    assert sug.target_id == consumer.id
    assert len(sug.paths) == 2  # alternate provenance kept
    sigs = {tuple(h.via_dependency_id for h in p) for p in sug.paths}
    assert len(sigs) == 2


def test_cross_environment_filter(db_session):
    db = db_session
    prod = _env(db, "PROD")
    qa = _env(db, "QA")
    oracle = _infra(db, "ora")
    claims = _app(db, "claims")
    _edge(
        db,
        from_type="application",
        from_id=claims.id,
        to_type="infra_component",
        to_id=oracle.id,
        from_environment_id=qa.id,
        to_environment_id=qa.id,  # provider env QA
        origin="manual",
    )
    db.commit()
    # Seed Oracle PROD — edge pins to QA provider env → no match
    miss = analyze_downstream_impacts(
        db, seeds=[ImpactRef("infra_component", oracle.id, prod.id)]
    )
    assert miss.downstream == []
    hit = analyze_downstream_impacts(
        db, seeds=[ImpactRef("infra_component", oracle.id, qa.id)]
    )
    assert len(hit.downstream) == 1


def test_absent_deps_warning_not_proof_of_none(db_session):
    db = db_session
    lonely = _app(db, "lonely")
    db.commit()
    result = analyze_downstream_impacts(
        db, seeds=[ImpactRef("application", lonely.id, None)]
    )
    absent = next(w for w in result.warnings if w.code == "no_known_dependents")
    assert "not proof" in absent.message.lower()


def test_stale_imported_edge_warning(db_session):
    db = db_session
    provider = _app(db, "p")
    consumer = _app(db, "c")
    dep = _edge(
        db,
        from_type="application",
        from_id=consumer.id,
        to_type="application",
        to_id=provider.id,
        origin="import",
    )
    # Force old updated_at
    dep.updated_at = datetime.now(timezone.utc) - timedelta(days=120)
    db.commit()
    result = analyze_downstream_impacts(
        db, seeds=[ImpactRef("application", provider.id, None)]
    )
    sug = result.downstream[0]
    assert any("verify" in w.lower() or "stale" in w.lower() or ">" in w for w in sug.warnings)
