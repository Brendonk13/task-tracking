from datetime import datetime

from ninja import Schema

from tracker.models import Priority


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
    actor_session_id: str


class TicketDetail(Schema):
    id: int
    title: str
    description: str
    priority: Priority
    created_at: datetime
    updated_at: datetime
