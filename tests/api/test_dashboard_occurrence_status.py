"""Dashboard must use per-occurrence status — siblings do not inherit In progress."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.api.test_occurrence_lifecycle import _bootstrap, _create_weekly_series


def test_dashboard_upcoming_sibling_not_in_progress_from_prior(client):
    pub, _other, _admin, app, env = _bootstrap(client)

    starts = datetime.now(timezone.utc).replace(microsecond=0, minute=0, second=0) + timedelta(
        days=1
    )
    created = _create_weekly_series(
        client, pub, app, env, starts=starts, title="Weekly sibling"
    )
    assert created.status_code == 201, created.text
    eid = created.json()["id"]

    occs = client.get(
        f"/api/v1/events/{eid}/occurrences",
        params={
            "from": (starts - timedelta(hours=1)).isoformat(),
            "to": (starts + timedelta(days=21)).isoformat(),
        },
        headers=pub,
    ).json()
    assert len(occs) >= 2
    first, second = occs[0], occs[1]

    assert (
        client.post(
            f"/api/v1/events/{eid}/occurrences/transition",
            json={"original_starts_at": first["original_starts_at"], "status": "in_progress"},
            headers=pub,
        ).status_code
        == 200
    )

    dash = client.get("/api/v1/dashboard/summary", headers=pub).json()
    weekly_up = [i for i in dash["upcoming"]["items"] if i.get("title") == "Weekly sibling"]

    def _matches(item: dict, orig_iso: str) -> bool:
        raw = item.get("occurrence_starts_at")
        if not raw:
            return False
        a = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        b = datetime.fromisoformat(orig_iso.replace("Z", "+00:00"))
        return abs((a - b).total_seconds()) < 1

    second_rows = [i for i in weekly_up if _matches(i, second["original_starts_at"])]
    assert second_rows, f"expected upcoming sibling, got {weekly_up!r}"
    assert second_rows[0]["status"] == "scheduled"

    # First is in_progress but window is still future — must not appear as upcoming In progress
    first_up = [i for i in weekly_up if _matches(i, first["original_starts_at"])]
    assert first_up == []

    # Calendar also uses per-occurrence status
    cal = client.get(
        "/api/v1/calendar/events",
        params={
            "view": "agenda",
            "from": (starts - timedelta(hours=1)).isoformat(),
            "to": (starts + timedelta(days=21)).isoformat(),
        },
        headers=pub,
    ).json()
    cal_second = [
        c
        for c in cal
        if c.get("title") == "Weekly sibling"
        and c.get("occurrence_starts_at")
        and _matches(c, second["original_starts_at"])
    ]
    assert cal_second
    assert cal_second[0]["status"] == "scheduled"
