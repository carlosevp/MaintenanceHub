from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from maintenancehub_api.schemas.common import ORMModel


class TargetIn(BaseModel):
    target_type: str
    target_id: str


class TargetOut(ORMModel):
    id: str
    target_type: str
    target_id: str


class ReminderIn(BaseModel):
    offset_minutes: int


class ReminderOut(ORMModel):
    id: str
    offset_minutes: int


class SubscriptionCreate(BaseModel):
    destination_type: str = "email_address"  # email_address | teams_bridge_channel
    destination: str = Field(min_length=1, max_length=320)
    bridge_channel_key: Optional[str] = None
    digest_mode: str = "none"
    targets: list[TargetIn] = Field(default_factory=list)
    reminders: list[ReminderIn] = Field(default_factory=list)


class SubscriptionUpdate(BaseModel):
    is_active: Optional[bool] = None
    destination_type: Optional[str] = None
    destination: Optional[str] = None
    bridge_channel_key: Optional[str] = None
    digest_mode: Optional[str] = None


class SubscriptionOut(ORMModel):
    id: str
    user_id: str
    is_active: bool
    digest_mode: str
    destination_type: str
    destination: str
    bridge_channel_key: Optional[str] = None
    targets: list[TargetOut] = Field(default_factory=list)
    reminders: list[ReminderOut] = Field(default_factory=list)


class DeliveryOut(ORMModel):
    id: str
    idempotency_key: str
    channel: str
    destination_type: str
    destination: str
    subject: Optional[str] = None
    body: Optional[str] = None
    body_html: Optional[str] = None
    body_plain: Optional[str] = None
    template_id: Optional[str] = None
    template_version: Optional[int] = None
    rendered_payload: Optional[dict] = None
    status: str
    attempt_count: int
    last_error: Optional[str] = None
    provider_message_id: Optional[str] = None
    event_id: Optional[str] = None
    subscription_id: Optional[str] = None


class TemplateOut(ORMModel):
    id: str
    key: str
    name: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[str] = None
    status: str = "active"
    channel: str
    subject_template: str
    body_template: str
    body_plain_template: Optional[str] = None
    body_html_template: Optional[str] = None
    version: int = 1
    is_system: bool = False
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TemplatePatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[str] = None
    channel: Optional[str] = None
    subject_template: Optional[str] = None
    body_template: Optional[str] = None
    body_plain_template: Optional[str] = None
    body_html_template: Optional[str] = None
    change_note: Optional[str] = None


class TemplateCreate(BaseModel):
    key: str
    name: str
    event_type: str
    subject_template: str
    body_plain_template: str
    body_html_template: Optional[str] = None
    channel: str = "smtp"
    description: Optional[str] = None
    activate: bool = True


class TemplateCloneRequest(BaseModel):
    new_key: Optional[str] = None
    new_name: Optional[str] = None


class TemplatePreviewRequest(BaseModel):
    context: dict = Field(default_factory=dict)
    subject_template: Optional[str] = None
    body_plain_template: Optional[str] = None
    body_html_template: Optional[str] = None


class TemplateRestoreRequest(BaseModel):
    version: int


class TestSendRequest(BaseModel):
    template_key: str = "event.created"
    destination_type: str = "email_address"
    destination: str
    bridge_channel_key: Optional[str] = None
    teams_target_email: Optional[str] = None
    context: dict = Field(default_factory=dict)
    # When true (default), prefer demo capture / log sink semantics in the response note.
    capture_only: bool = False


class CalendarTokenCreate(BaseModel):
    scopes: list[str] = Field(default_factory=lambda: ["favorites", "subscriptions"])
    label: Optional[str] = None


class CalendarTokenOut(ORMModel):
    id: str
    scopes: list
    label: Optional[str] = None
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    created_at: Optional[str] = None


class CalendarTokenCreated(CalendarTokenOut):
    token: str  # raw secret once
    feed_url: str


class JobOut(ORMModel):
    id: str
    job_type: str
    status: str
    attempt_count: int
    last_error: Optional[str] = None
    leased_by: Optional[str] = None
    idempotency_key: Optional[str] = None
