"""Project/label tags on a ticket (section 1 "Tag").

A ticket has at most one ``project`` tag and any number of ``label`` tags.
Tags are created on first use. ``labels`` are always de-duplicated and sorted.
"""

from tracker import models


def normalize_labels(labels: list[str]) -> list[str]:
    return sorted(set(labels))


def project_of(ticket: models.Ticket) -> str | None:
    for tag in ticket.tags.all():
        if tag.kind == models.TagKind.PROJECT:
            return tag.name
    return None


def labels_of(ticket: models.Ticket) -> list[str]:
    return normalize_labels(
        [tag.name for tag in ticket.tags.all() if tag.kind == models.TagKind.LABEL]
    )


def _tag(kind: models.TagKind, name: str) -> models.Tag:
    tag, _created = models.Tag.objects.get_or_create(kind=kind, name=name)
    return tag


def set_tags(ticket: models.Ticket, project: str | None, labels: list[str]) -> None:
    tags = [_tag(models.TagKind.LABEL, name) for name in normalize_labels(labels)]
    if project is not None:
        tags.append(_tag(models.TagKind.PROJECT, project))
    ticket.tags.set(tags)
