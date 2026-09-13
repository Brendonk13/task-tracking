from datetime import datetime

from ninja import Schema


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
