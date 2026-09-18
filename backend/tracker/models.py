from django.db import models


class SessionPurpose(models.TextChoices):
    MANUAL = "manual"
    TICKET_BRIEF = "ticket_brief"
    PR_TRIAGE = "pr_triage"


class SessionStatus(models.TextChoices):
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"


class Session(models.Model):
    """A Claude Code session, either registering itself or started by this app.

    A session a human started can only describe itself, so everything about how it was
    launched is null and its ``purpose`` is ``manual``. A managed session is the other
    way round: the backend chose the model, the effort and the work, so those columns
    are filled in and ``status`` tracks the process this app is holding open.
    """

    session_id = models.CharField(max_length=255, primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    directory = models.TextField()
    last_message = models.TextField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    # The ticket this session is working on, as the session last reported it.
    ticket = models.ForeignKey(
        "Ticket", null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions"
    )
    # Why this app started the session. ``manual`` means it started itself.
    purpose = models.CharField(
        max_length=20, choices=SessionPurpose.choices, default=SessionPurpose.MANUAL
    )
    # How it was launched and how it ended: null for a session we did not launch, since
    # a session that registers itself never tells us any of this.
    model = models.CharField(max_length=50, null=True, blank=True)
    effort = models.CharField(max_length=20, null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=SessionStatus.choices, null=True, blank=True
    )
    result_summary = models.TextField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cron_run = models.ForeignKey(
        "CronRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class Priority(models.TextChoices):
    URGENT = "urgent"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class TagKind(models.TextChoices):
    PROJECT = "project"
    LABEL = "label"


class Tag(models.Model):
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=TagKind.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "name"], name="unique_tag_kind_name")
        ]


class Status(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_builtin = models.BooleanField(default=False)
    position = models.PositiveIntegerField(null=True, blank=True)


class Ticket(models.Model):
    title = models.CharField(max_length=500)
    # One level only: a ticket with a parent may not itself be a parent. The API
    # enforces that; the column cannot.
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    description = models.TextField(default="", blank=True)
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.NONE
    )
    linear_url = models.URLField(max_length=2000, null=True, blank=True)
    # Where the ticket came from, when it came from Linear: the issue's UUID, and the
    # human key ("CON-7") people actually say out loud. Both are null for a ticket
    # someone created here, and unique so one issue cannot be imported twice.
    linear_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    linear_identifier = models.CharField(max_length=50, null=True, blank=True, unique=True)
    status = models.ForeignKey(
        Status, null=True, blank=True, on_delete=models.PROTECT, related_name="tickets"
    )
    needs_human_eyes = models.BooleanField(default=False)
    tags = models.ManyToManyField(Tag, related_name="tickets", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class TimelineKind(models.TextChoices):
    COMMENT = "comment"
    STATUS_CHANGE = "status_change"
    FLAG_CHANGE = "flag_change"
    FIELD_CHANGE = "field_change"


class TimelineEntry(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="timeline")
    kind = models.CharField(max_length=20, choices=TimelineKind.choices)
    actor_session_id = models.CharField(max_length=255)
    body = models.TextField()
    from_status = models.CharField(max_length=100, null=True, blank=True)
    to_status = models.CharField(max_length=100, null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class TaskState(models.TextChoices):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


# States in which a task no longer holds up the tasks that depend on it.
FINISHED_TASK_STATES = (TaskState.DONE, TaskState.CANCELLED)


class Task(models.Model):
    """One small piece of a ticket's work, e.g. "write the migration".

    Tasks on a ticket form a DAG through ``depends_on``. The API keeps it acyclic and
    within one ticket; the columns cannot.
    """

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=500)
    description = models.TextField(default="", blank=True)
    state = models.CharField(
        max_length=20, choices=TaskState.choices, default=TaskState.TODO
    )
    depends_on = models.ManyToManyField(
        "self",
        through="TaskDependency",
        through_fields=("task", "depends_on"),
        symmetrical=False,
        related_name="dependents",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]


class TaskDependency(models.Model):
    """An edge ``task -> depends_on``: ``task`` cannot be finished before ``depends_on``."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="dependency_links")
    depends_on = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="dependent_links"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task", "depends_on"], name="unique_task_dependency"
            ),
            models.CheckConstraint(
                condition=~models.Q(task=models.F("depends_on")),
                name="task_cannot_depend_on_itself",
            ),
        ]


class TaskHistoryKind(models.TextChoices):
    STATE_CHANGE = "state_change"
    FIELD_CHANGE = "field_change"


class TaskHistoryEntry(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="history")
    kind = models.CharField(max_length=20, choices=TaskHistoryKind.choices)
    actor_session_id = models.CharField(max_length=255)
    body = models.TextField()
    from_state = models.CharField(max_length=20, null=True, blank=True)
    to_state = models.CharField(max_length=20, null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class CronRunStatus(models.TextChoices):
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"


class CronRunTrigger(models.TextChoices):
    API = "api"
    COMMAND = "command"


class CronRun(models.Model):
    """One pass of the cron over its configured work.

    A row exists from the moment a run starts, so a run that dies mid-flight is still
    visible as ``running`` rather than vanishing. ``pid`` is the worker process, kept so
    a later slice can tell a stalled run from a live one; it is null when the run is not
    driven by a detached worker.
    """

    status = models.CharField(
        max_length=20, choices=CronRunStatus.choices, default=CronRunStatus.RUNNING
    )
    trigger = models.CharField(max_length=20, choices=CronRunTrigger.choices)
    summary = models.TextField(default="", blank=True)
    error = models.TextField(default="", blank=True)
    pid = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # Newest first: the API and the UI both want the latest run at the top.
        ordering = ["-started_at", "-id"]


class AlertKind(models.TextChoices):
    NEW_TICKET = "new_ticket"
    PR_TRIAGED = "pr_triaged"
    PR_UNLINKED = "pr_unlinked"
    CRON_ERROR = "cron_error"


class Alert(models.Model):
    """Something that happened unattended and wants a human to look at it.

    The cron runs without anyone watching, so anything it decides on its own — a ticket
    it imported, a step it had to skip — leaves an alert behind. Every link is nullable
    because an alert is about the event, not about any one row: a ``cron_error`` names a
    run and no ticket, a ``new_ticket`` names a ticket and no run.
    """

    kind = models.CharField(max_length=20, choices=AlertKind.choices)
    message = models.TextField()
    ticket = models.ForeignKey(
        Ticket, null=True, blank=True, on_delete=models.CASCADE, related_name="alerts"
    )
    session = models.ForeignKey(
        Session, null=True, blank=True, on_delete=models.SET_NULL, related_name="alerts"
    )
    cron_run = models.ForeignKey(
        CronRun, null=True, blank=True, on_delete=models.CASCADE, related_name="alerts"
    )
    # Null until a human clears it; the column doubles as "is this still open?".
    dismissed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Newest first: the UI shows the most recent alerts at the top.
        ordering = ["-created_at", "-id"]


class TicketBrief(models.Model):
    """Where the brief for a ticket landed on disk, as the session that wrote it said.

    The brief is two files a Claude Code session wrote, not rows in this database, so
    all that is kept here is the pointer a human opens it by. One per ticket, because a
    later run describes the same ticket again and replaces what it said.
    """

    ticket = models.OneToOneField(Ticket, on_delete=models.CASCADE, related_name="brief")
    md_path = models.TextField()
    html_path = models.TextField()
    # The run that produced it, kept so a reader can resume the transcript behind a
    # brief; null once that session row is gone.
    session = models.ForeignKey(
        Session, null=True, blank=True, on_delete=models.SET_NULL, related_name="briefs"
    )
    created_at = models.DateTimeField(auto_now_add=True)
