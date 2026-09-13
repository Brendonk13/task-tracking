from datetime import datetime

from ninja import Schema

from tracker.models import Priority, TagKind


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


class TicketDetail(Schema):
    id: int
    title: str
    description: str
    priority: Priority
    project: str | None
    labels: list[str]
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_project(obj) -> str | None:
        tag = obj.tags.filter(kind=TagKind.PROJECT).first()
        return tag.name if tag else None

    @staticmethod
    def resolve_labels(obj) -> list[str]:
        return sorted(obj.tags.filter(kind=TagKind.LABEL).values_list("name", flat=True))
