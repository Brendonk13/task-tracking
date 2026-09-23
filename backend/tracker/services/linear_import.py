"""Turning a Linear issue into a ticket, whoever asked for it.

Two callers bring issues here: the cron, which sweeps the Todo column every pass, and a
person who pastes a list of Linear URLs into ``POST /tickets/import``. Both mean the same
thing by "import", so the rules live once: an issue we already track is left alone, an
issue a human raised by hand is adopted, and anything else is born as a new ticket.
"""

from tracker import models
from tracker.integrations import linear
from tracker.services import linear_identifiers, tags

IMPORTED = "imported"
ADOPTED = "adopted"
EXISTS = "exists"
INVALID_URL = "invalid_url"
NOT_FOUND = "not_found"

# Linear grades urgency 1 (most urgent) to 4, with 0 meaning "nobody said".
PRIORITY_BY_LINEAR = {
    0: models.Priority.NONE,
    1: models.Priority.URGENT,
    2: models.Priority.HIGH,
    3: models.Priority.MEDIUM,
    4: models.Priority.LOW,
}


def announce_new_ticket(ticket: models.Ticket) -> models.Alert:
    """Tell a human a ticket was born while nobody was watching.

    The import is the only actor here, so the alerts page is where the news lands. The
    message names the issue the way Linear does — identifier then title — because that
    is what a person recognises it by, and the link carries the ticket itself.
    """
    return models.Alert.objects.create(
        kind=models.AlertKind.NEW_TICKET,
        ticket=ticket,
        message=f"Imported {ticket.linear_identifier}: {ticket.title}",
    )


class Importer:
    """Imports issues against one snapshot of the tickets we already have.

    The snapshot is taken once, so a sweep over fifty issues reads the ticket table
    once rather than fifty times. Each import updates it, so the same issue offered
    twice is imported once and reported as existing the second time.
    """

    def __init__(self):
        self._known = dict(
            models.Ticket.objects.filter(linear_id__isnull=False).values_list(
                "linear_id", "id"
            )
        )
        self._unlinked: dict[str, models.Ticket] = {}
        for ticket in models.Ticket.objects.filter(linear_id__isnull=True):
            identifier = ticket.linear_identifier or linear_identifiers.identifier_in_url(
                ticket.linear_url
            )
            if identifier:
                self._unlinked.setdefault(identifier.upper(), ticket)

    def import_issue(self, issue: linear.LinearIssue) -> tuple[str, int]:
        """Bring ``issue`` in, and say how: ``imported``, ``adopted`` or ``exists``.

        An import is a birth, not an edit: the ticket arrives already holding these
        values, so no ``field_change`` timeline entry is written for them. There is
        nobody to attribute such a change to, and a reader wants the issue's history
        from Linear, not a replay of the import.

        An issue a human already raised a ticket for by hand — recognised by the
        identifier they pasted in as a Linear URL — is adopted instead of duplicated:
        it gains the issue's ``linear_id`` and ``linear_identifier``, and keeps
        everything the human wrote, which they may have worded that way on purpose.
        An issue that already has a ticket is left untouched — not re-saved with
        identical values, which would move ``updated_at`` and make every pass look
        like a change.
        """
        if issue.id in self._known:
            return EXISTS, self._known[issue.id]

        adopted = self._unlinked.pop(issue.identifier.upper(), None)
        if adopted is not None:
            adopted.linear_id = issue.id
            adopted.linear_identifier = issue.identifier
            adopted.save(update_fields=["linear_id", "linear_identifier"])
            self._known[issue.id] = adopted.id
            return ADOPTED, adopted.id

        ticket = models.Ticket.objects.create(
            title=issue.title,
            description=issue.description,
            priority=PRIORITY_BY_LINEAR[issue.priority],
            linear_url=issue.url,
            linear_id=issue.id,
            linear_identifier=issue.identifier,
        )
        tags.set_tags(ticket, issue.project, issue.labels)
        announce_new_ticket(ticket)
        self._known[issue.id] = ticket.id
        return IMPORTED, ticket.id


def import_urls(client: linear.LinearClient, urls: list[str]) -> list[dict]:
    """Import the issues a person pasted as Linear URLs, one result per distinct URL.

    Each URL is answered on its own, so one typo does not cost the rest of the list.
    The Todo rule the cron keeps does not apply: a person who names an issue wants it,
    whatever state it is in. A URL pasted twice is one request, so it is answered once.
    A Linear outage is not any one URL's fault, so ``LinearError`` is left to the
    caller rather than written against whichever URL happened to be asked first.
    """
    importer = Importer()
    results = []
    for url in dict.fromkeys(url.strip() for url in urls):
        identifier = linear_identifiers.identifier_in_url(url)
        if identifier is None:
            results.append(
                _result(url, INVALID_URL, message="Not a Linear issue URL.")
            )
            continue
        issue = client.issue(identifier)
        if issue is None:
            results.append(
                _result(url, NOT_FOUND, message=f"Linear has no issue {identifier}.")
            )
            continue
        outcome, ticket_id = importer.import_issue(issue)
        results.append(_result(url, outcome, ticket_id=ticket_id))
    return results


def _result(url: str, outcome: str, *, ticket_id=None, message=None) -> dict:
    return {"url": url, "outcome": outcome, "ticket_id": ticket_id, "message": message}
