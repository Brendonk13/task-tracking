from django.db import models


class Session(models.Model):
    session_id = models.CharField(max_length=255, primary_key=True)
    name = models.CharField(max_length=100)
    directory = models.TextField()
    last_message = models.TextField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
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


class Ticket(models.Model):
    title = models.CharField(max_length=500)
    description = models.TextField(default="", blank=True)
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.NONE
    )
    tags = models.ManyToManyField(Tag, related_name="tickets", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
