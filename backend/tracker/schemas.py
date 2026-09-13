from datetime import datetime

from ninja import Schema
from pydantic import field_validator

from tracker.models import Priority, TagKind
from tracker.services import actors


class SessionIn(Schema):
    directory: str
    last_message: str | None = None
    last_message_at: datetime | None = None


class Session(Schema):
    session_id: str
    name: str
    directory: str
    last_message: str | None
    last_message_at: datetime | None
    created_at: datetime


class TicketCreate(Schema):
    title: str
    description: str = ""
    priority: Priority = Priority.NONE
    linear_url: str | None = None
    project: str | None = None
    labels: list[str] = []
    actor_session_id: str


class TicketPatch(Schema):
    title: str | None = None
    description: str | None = None
    priority: Priority | None = None
    linear_url: str | None = None
    project: str | None = None
    labels: list[str] | None = None
    actor_session_id: str


class StatusChangeIn(Schema):
    status: str
    reason: str
    actor_session_id: str

    @field_validator("status")
    @classmethod
    def strip_status(cls, value: str) -> str:
        return value.strip()

    @field_validator("status", "reason")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return value


class Actor(Schema):
    session_id: str
    name: str
    directory: str | None


class TimelineEntry(Schema):
    id: int
    kind: str
    actor: Actor
    body: str
    created_at: datetime
    from_status: str | None
    to_status: str | None
    reason: str | None

    @staticmethod
    def resolve_actor(obj) -> dict:
        return actors.actor_view(obj.actor_session_id)


class TicketListItem(Schema):
    id: int
    title: str
    priority: Priority
    status: str | None
    linear_url: str | None
    project: str | None
    labels: list[str]
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_status(obj) -> str | None:
        return obj.status.name if obj.status else None

    @staticmethod
    def resolve_project(obj) -> str | None:
        tag = obj.tags.filter(kind=TagKind.PROJECT).first()
        return tag.name if tag else None

    @staticmethod
    def resolve_labels(obj) -> list[str]:
        return sorted(obj.tags.filter(kind=TagKind.LABEL).values_list("name", flat=True))


class TicketDetail(TicketListItem):
    description: str
    timeline: list[TimelineEntry]

    @staticmethod
    def resolve_timeline(obj):
        return obj.timeline.order_by("created_at", "id")


class StatusItem(Schema):
    name: str
    is_builtin: bool
