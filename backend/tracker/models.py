from django.db import models


class Session(models.Model):
    session_id = models.CharField(max_length=255, primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    directory = models.TextField()
    last_message = models.TextField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    # The ticket this session is working on, as the session last reported it.
    ticket = models.ForeignKey(
        "Ticket", null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions"
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
