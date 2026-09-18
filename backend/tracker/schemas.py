from datetime import datetime, timezone

from ninja import Schema
from pydantic import Field, field_validator, model_validator

from tracker.models import (
    FINISHED_TASK_STATES,
    AlertKind,
    CronRunStatus,
    CronRunTrigger,
    Priority,
    TaskHistoryKind,
    TaskState,
    TimelineKind,
)
from tracker.services import actors, tags


class SessionIn(Schema):
    directory: str
    last_message: str | None = None
    last_message_at: datetime | None = None
    ticket_id: int | None = None

    @field_validator("last_message_at")
    @classmethod
    def naive_is_utc(cls, value: datetime | None) -> datetime | None:
        # A10: naive timestamps are treated as UTC.
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class Session(Schema):
    session_id: str
    name: str
    directory: str
    last_message: str | None
    last_message_at: datetime | None
    ticket_id: int | None
    created_at: datetime


def _blank_to_none(value: str | None) -> str | None:
    """``""`` (after stripping) means "no value" for optional string fields."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _stripped_non_empty(value: str) -> str:
    """Required free-text fields: strip, then reject whitespace-only with 422."""
    value = value.strip()
    if not value:
        raise ValueError("must not be empty")
    return value


class TicketCreate(Schema):
    title: str
    description: str = ""
    priority: Priority = Priority.NONE
    linear_url: str | None = None
    project: str | None = None
    labels: list[str] = []
    parent_id: int | None = None
    actor_session_id: str

    @field_validator("title")
    @classmethod
    def title_non_empty(cls, value: str) -> str:
        return _stripped_non_empty(value)

    @field_validator("project", "linear_url")
    @classmethod
    def blank_is_none(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, value: list[str]) -> list[str]:
        return tags.normalize_labels(value)


PATCH_NON_NULLABLE = ("title", "description", "priority", "labels")


class TicketPatch(Schema):
    """A4: per-key replace; omitted keys are untouched. Only ``project`` and
    ``linear_url`` may be cleared with an explicit ``null``."""

    title: str | None = None
    description: str | None = None
    priority: Priority | None = None
    linear_url: str | None = None
    project: str | None = None
    labels: list[str] | None = None
    parent_id: int | None = None
    actor_session_id: str

    @field_validator("title")
    @classmethod
    def title_non_empty(cls, value: str | None) -> str | None:
        return value if value is None else _stripped_non_empty(value)

    @field_validator("project", "linear_url")
    @classmethod
    def blank_is_none(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, value: list[str] | None) -> list[str] | None:
        return value if value is None else tags.normalize_labels(value)

    @model_validator(mode="after")
    def reject_null_on_non_nullable(self):
        # ninja wraps the request body in a DjangoGetter before "before"-mode
        # validators run, so we check explicitly-sent keys via model_fields_set.
        nulled = [
            k for k in PATCH_NON_NULLABLE
            if k in self.model_fields_set and getattr(self, k) is None
        ]
        if nulled:
            raise ValueError(f"{', '.join(nulled)}: null is not allowed")
        return self


class StatusChangeIn(Schema):
    status: str = Field(max_length=100)  # matches Status.name
    reason: str
    actor_session_id: str

    @field_validator("status", "reason")
    @classmethod
    def strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("status", "reason")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return value


class CommentIn(Schema):
    body: str
    actor_session_id: str

    @field_validator("body")
    @classmethod
    def non_empty(cls, value: str) -> str:
        return _stripped_non_empty(value)


class NeedsHumanEyesIn(Schema):
    value: bool
    reason: str | None = None
    actor_session_id: str

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class Actor(Schema):
    session_id: str
    name: str
    directory: str | None


class TimelineEntry(Schema):
    id: int
    kind: TimelineKind
    actor: Actor
    body: str
    created_at: datetime
    from_status: str | None
    to_status: str | None
    reason: str | None

    @staticmethod
    def resolve_actor(obj) -> dict:
        pre_resolved = getattr(obj, "actor", None)
        return pre_resolved or actors.actor_view(obj.actor_session_id)


class TicketRef(Schema):
    """Just enough of a ticket to render a link to it."""

    id: int
    title: str


class TicketListItem(Schema):
    id: int
    title: str
    priority: Priority
    status: str | None
    needs_human_eyes: bool
    linear_url: str | None
    linear_identifier: str | None
    project: str | None
    labels: list[str]
    parent_id: int | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_status(obj) -> str | None:
        return obj.status.name if obj.status else None

    @staticmethod
    def resolve_project(obj) -> str | None:
        return tags.project_of(obj)

    @staticmethod
    def resolve_labels(obj) -> list[str]:
        return tags.labels_of(obj)


class TaskCreate(Schema):
    title: str
    description: str = ""
    depends_on: list[int] = []
    actor_session_id: str

    @field_validator("title")
    @classmethod
    def title_non_empty(cls, value: str) -> str:
        return _stripped_non_empty(value)

    @field_validator("depends_on")
    @classmethod
    def dedupe_depends_on(cls, value: list[int]) -> list[int]:
        return sorted(set(value))


TASK_PATCH_FIELDS = ("title", "description", "depends_on")


class TaskPatch(Schema):
    """Per-key replace, like ``TicketPatch``. No task field is nullable, so an explicit
    ``null`` on any of them is rejected."""

    title: str | None = None
    description: str | None = None
    depends_on: list[int] | None = None
    actor_session_id: str

    @field_validator("title")
    @classmethod
    def title_non_empty(cls, value: str | None) -> str | None:
        return value if value is None else _stripped_non_empty(value)

    @field_validator("depends_on")
    @classmethod
    def dedupe_depends_on(cls, value: list[int] | None) -> list[int] | None:
        return value if value is None else sorted(set(value))

    @model_validator(mode="after")
    def reject_null(self):
        nulled = [
            k for k in TASK_PATCH_FIELDS
            if k in self.model_fields_set and getattr(self, k) is None
        ]
        if nulled:
            raise ValueError(f"{', '.join(nulled)}: null is not allowed")
        return self


class TaskStateIn(Schema):
    state: TaskState
    reason: str | None = None
    actor_session_id: str

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class TaskHistoryEntry(Schema):
    id: int
    kind: TaskHistoryKind
    actor: Actor
    body: str
    created_at: datetime
    from_state: TaskState | None
    to_state: TaskState | None
    reason: str | None

    @staticmethod
    def resolve_actor(obj) -> dict:
        pre_resolved = getattr(obj, "actor", None)
        return pre_resolved or actors.actor_view(obj.actor_session_id)


class Task(Schema):
    id: int
    ticket_id: int
    title: str
    description: str
    state: TaskState
    depends_on: list[int]
    blocked_by: list[int]
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_depends_on(obj) -> list[int]:
        # Uses the prefetch cache set up by the tasks router.
        return sorted(dep.id for dep in obj.depends_on.all())

    @staticmethod
    def resolve_blocked_by(obj) -> list[int]:
        """The subset of ``depends_on`` that is not yet done or cancelled."""
        return sorted(
            dep.id for dep in obj.depends_on.all() if dep.state not in FINISHED_TASK_STATES
        )


class TaskDetail(Task):
    history: list[TaskHistoryEntry]

    @staticmethod
    def resolve_history(obj):
        # Ordered by TaskHistoryEntry.Meta.ordering; uses the prefetch cache when present.
        return obj.history.all()


class TicketDetail(TicketListItem):
    description: str
    parent: TicketRef | None
    children: list[TicketListItem]
    tasks: list[Task]
    timeline: list[TimelineEntry]

    @staticmethod
    def resolve_children(obj):
        # Oldest first; uses the prefetch cache set up by the tickets router.
        return obj.children.all()

    @staticmethod
    def resolve_tasks(obj):
        # Oldest first; uses the prefetch cache set up by the tickets router.
        return obj.tasks.all()

    @staticmethod
    def resolve_timeline(obj):
        # Ordered by TimelineEntry.Meta.ordering; uses the prefetch cache when present.
        return obj.timeline.all()


class StatusItem(Schema):
    name: str
    is_builtin: bool


class TicketsSummary(Schema):
    needs_human_eyes_count: int


class CronRun(Schema):
    id: int
    status: CronRunStatus
    trigger: CronRunTrigger
    summary: str
    error: str
    pid: int | None
    started_at: datetime
    created_at: datetime
    finished_at: datetime | None


class Alert(Schema):
    id: int
    kind: AlertKind
    message: str
    # Nested rather than a bare id: the alerts page renders a link, and a title is the
    # only thing a person can recognise a ticket by.
    ticket: TicketRef | None
    session_id: str | None
    cron_run_id: int | None
    dismissed_at: datetime | None
    created_at: datetime
