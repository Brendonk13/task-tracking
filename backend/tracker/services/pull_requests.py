"""Pull requests: reading the ticket a PR is work on out of what GitHub says about it.

Nobody tells this app which ticket a PR belongs to. The link has to be guessed from the
Linear identifier the author already wrote down somewhere on the PR, which is why the
guess is only ever accepted when it names a ticket this app already knows.
"""

from tracker import models
from tracker.services import actors, changes
from tracker.services.linear_identifiers import identifier_in_url, identifiers_in


def tickets_by_identifier() -> dict[str, models.Ticket]:
    """Every ticket this app knows, keyed by the Linear identifier it answers to.

    A ticket raised by hand has no ``linear_identifier`` — the API never accepts one —
    so the identifier a human pasted in as a Linear URL counts too, the same way the
    import reads it when it adopts such a ticket.
    """
    known: dict[str, models.Ticket] = {}
    for ticket in models.Ticket.objects.all():
        identifier = ticket.linear_identifier or identifier_in_url(ticket.linear_url)
        if identifier:
            known.setdefault(identifier.upper(), ticket)
    return known


def ticket_for(pull_request: models.PullRequest, known: dict[str, models.Ticket]):
    """The ticket a PR names, or ``None``.

    The branch is asked first, then the title, then the body: the branch is the one
    place the identifier is chosen deliberately, while a body often mentions other
    issues in passing — the PR that unskips a test names the issue that fixed the race
    it used to hit. An identifier naming no ticket here links nothing rather than
    something that merely looks close.
    """
    for text in (pull_request.branch, pull_request.title, pull_request.body):
        for identifier in identifiers_in(text):
            ticket = known.get(identifier)
            if ticket is not None:
                return ticket
    return None


def link_to_tickets(pull_requests) -> list[models.PullRequest]:
    """Link each PR to the ticket it names, and say so on that ticket's timeline.

    The link is a change to the ticket made by nobody at the keyboard, so it is recorded
    under the reserved ``cron`` actor. Only a PR that is not already linked is touched:
    the cron sees the same open PRs every fifteen minutes, and a pass over unchanged
    work must leave no trace.
    """
    known = tickets_by_identifier()
    linked = []
    for pull_request in pull_requests:
        if pull_request.ticket_id is not None:
            continue
        ticket = ticket_for(pull_request, known)
        if ticket is None:
            flag_unlinked(pull_request)
            continue
        link(pull_request, ticket, actors.CRON, actors.CRON)
        linked.append(pull_request)
    return linked


def link(pull_request: models.PullRequest, ticket: models.Ticket, actor_session_id: str,
         actor_name: str) -> bool:
    """Say this PR is work on this ticket, and write that on the ticket's history.

    The link is a change to the ticket as much as to the PR — it is how the ticket's
    history explains where the code came from — so it always leaves the same entry,
    whether the matcher made the link or a person did (C3.7); only the actor differs.

    Asking for the link a PR already has changes nothing, so nothing is written: the
    cron re-reads the same open PRs every fifteen minutes, and a person clicking twice
    must not double the history either.
    """
    if pull_request.ticket_id == ticket.id:
        return False
    pull_request.ticket = ticket
    pull_request.save(update_fields=["ticket"])
    models.TimelineEntry.objects.create(
        ticket=ticket,
        kind=models.TimelineKind.FIELD_CHANGE,
        actor_session_id=actor_session_id,
        body=changes.field_change_body(
            actor_name, "pull request", None, f"#{pull_request.number}"
        ),
    )
    return True


def flag_unlinked(pull_request: models.PullRequest) -> models.Alert | None:
    """Raise the standing flag that a PR names no ticket here, once.

    A PR nobody can place is something a person has to sort out — a ticket nobody
    raised, a typo'd branch — and it stays that way until they do. So the alert means
    "this PR is still unlinked", not "the cron noticed again": while an undismissed one
    is already standing for this PR, the pass adds nothing, and fifteen minutes of
    cron does not bury the alerts page. Once a human dismisses it and the PR is still
    unlinked, the flag goes back up.
    """
    standing = models.Alert.objects.filter(
        kind=models.AlertKind.PR_UNLINKED,
        pull_request=pull_request,
        dismissed_at__isnull=True,
    ).exists()
    if standing:
        return None
    return models.Alert.objects.create(
        kind=models.AlertKind.PR_UNLINKED,
        pull_request=pull_request,
        message=f"PR #{pull_request.number} matches no ticket: {pull_request.title}",
    )


def store_comments(client, pull_request: models.PullRequest) -> list[models.PRComment]:
    """Read every feed on a PR and keep what is new, in one insert.

    The cron looks at the same pull requests every fifteen minutes and GitHub answers
    with the whole conversation every time, so the insert ignores conflicts: a comment
    this app already holds is recognised by ``(pull_request, kind, github_id)`` and
    writes nothing, rather than doubling the thread and making every old comment look
    new to triage.

    A review with an empty body is not a comment. It is the wrapper GitHub creates
    around inline comments, and those comments arrive on their own feed, so storing it
    would invent something nobody wrote.
    """
    said = [
        comment
        for comment in client.comments(pull_request.repo, pull_request.number)
        if comment.body.strip()
    ]
    return models.PRComment.objects.bulk_create(
        [
            models.PRComment(
                pull_request=pull_request,
                kind=comment.kind,
                github_id=comment.github_id,
                in_reply_to_id=comment.in_reply_to_id,
                author=comment.author,
                is_bot=comment.is_bot,
                body=comment.body,
                path=comment.path,
                line=comment.line,
                url=comment.url,
            )
            for comment in said
        ],
        ignore_conflicts=True,
    )
