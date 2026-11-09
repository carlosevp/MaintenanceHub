from maintenancehub_api.domain.subscription_display import (
    LIFECYCLE_TO_NOTIFY,
    normalize_notify_events,
    subscription_allows_lifecycle,
)
from maintenancehub_api.models import Subscription


def test_normalize_empty_means_all():
    assert normalize_notify_events(None) == [
        "start",
        "extension",
        "cancellation",
        "completion",
    ]
    assert normalize_notify_events([]) == [
        "start",
        "extension",
        "cancellation",
        "completion",
    ]


def test_subscription_filters_lifecycle_interests():
    sub = Subscription(
        user_id="u",
        destination="a@b.c",
        notify_events=["cancellation"],
    )
    assert subscription_allows_lifecycle(sub, template_key="event.cancelled", reason="lifecycle")
    assert not subscription_allows_lifecycle(sub, template_key="event.extended", reason="lifecycle")
    assert not subscription_allows_lifecycle(sub, template_key="event.created", reason="lifecycle")


def test_lifecycle_map_covers_core_keys():
    for key in (
        "event.created",
        "event.extended",
        "event.cancelled",
        "event.completed",
        "event.reminder",
    ):
        assert key in LIFECYCLE_TO_NOTIFY
