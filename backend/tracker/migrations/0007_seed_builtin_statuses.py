"""Seed the ten built-in statuses (PLAN.md section 1) in canonical order."""

from django.db import migrations

BUILTIN_STATUSES = [
    "blocked",
    "needs-help",
    "planning",
    "implementing-plan",
    "diagnosing-ticket",
    "needs-clarification",
    "ready-for-pr",
    "merged",
    "tested-in-cloud",
    "done",
]


def seed_builtin_statuses(apps, schema_editor):
    Status = apps.get_model("tracker", "Status")
    for position, name in enumerate(BUILTIN_STATUSES):
        Status.objects.update_or_create(
            name=name, defaults={"is_builtin": True, "position": position}
        )


def unseed_builtin_statuses(apps, schema_editor):
    Status = apps.get_model("tracker", "Status")
    Status.objects.filter(name__in=BUILTIN_STATUSES, is_builtin=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0006_status"),
    ]

    operations = [
        migrations.RunPython(seed_builtin_statuses, unseed_builtin_statuses),
    ]
