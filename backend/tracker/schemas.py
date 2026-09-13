from datetime import datetime

from ninja import Schema

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
    project: str | None = None
    labels: list[str] = []
    actor_session_id: str


class TicketPatch(Schema):
    title: str | None = None
    description: str | None = None
    priority: Priority | None = None
    project: str | None = None
    labels: list[str] | None = None
    actor_session_id: str


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


class TicketDetail(Schema):
    id: int
    title: str
    description: str
    priority: Priority
    project: str | None
    labels: list[str]
    created_at: datetime
    updated_at: datetime
    timeline: list[TimelineEntry]

    @staticmethod
    def resolve_timeline(obj):
        return obj.timeline.order_by("created_at", "id")

    @staticmethod
    def resolve_project(obj) -> str | None:
        tag = obj.tags.filter(kind=TagKind.PROJECT).first()
        return tag.name if tag else None

    @staticmethod
    def resolve_labels(obj) -> list[str]:
        return sorted(obj.tags.filter(kind=TagKind.LABEL).values_list("name", flat=True))
