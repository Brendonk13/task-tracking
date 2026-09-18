"""The cron: one pass over the work this app watches, recorded as a ``CronRun``.

The command and (later) the API are both thin wrappers over ``start_run`` and
``execute``, so a run behaves the same however it was triggered.
"""

import re
import sys
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from tracker import models
from tracker.integrations import github, linear, processes
from tracker.services import briefs, pull_requests, tags, triage


def start_run(trigger: models.CronRunTrigger | str, pid: int | None = None) -> models.CronRun:
    """Record a run as ``running`` before any work happens, so a crash is still visible."""
    return models.CronRun.objects.create(trigger=trigger, pid=pid)


def running_run() -> models.CronRun | None:
    """The pass currently in flight, if any.

    ``one_running_cron_run`` means there is at most one, so callers can treat this as
    the run rather than as the newest of several.
    """
    return models.CronRun.objects.filter(status=models.CronRunStatus.RUNNING).first()


def reap_stale() -> list[models.CronRun]:
    """Close out runs whose worker process is gone, so the cron is not dead for ever.

    A worker can die without ever writing ``finished`` or ``failed`` — the machine
    reboots, the process is killed, the lid closes mid-run. The row then stays
    ``running`` and single flight refuses every later trigger, so crons stop until
    someone edits the database. The one question that can be answered from outside a
    dead worker is whether its pid is still a live process, asked at the ``pid_alive``
    boundary (S3); when it is not, the run is failed with an error saying so and an
    operator-visible ``cron_error`` names it. A run with no pid yet has not been
    abandoned — nothing was ever started for it to lose — so it is left alone.
    """
    reaped = []
    for run in models.CronRun.objects.filter(
        status=models.CronRunStatus.RUNNING, pid__isnull=False
    ):
        if processes.pid_alive(run.pid):
            continue
        run.status = models.CronRunStatus.FAILED
        run.error = f"Worker process {run.pid} is gone; the run was abandoned."
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at"])
        models.Alert.objects.create(
            kind=models.AlertKind.CRON_ERROR,
            cron_run=run,
            message=f"Cron run {run.id} was abandoned: worker process {run.pid} is gone.",
        )
        reaped.append(run)
    return reaped


WORKER_DIR_NAME = "crons"
"""The folder under ``CRON_WORK_DIR`` that keeps one log per detached worker."""


def worker_log_path(run: models.CronRun) -> Path:
    """Where a worker's output is kept, named after the run it belongs to.

    Nobody is watching the terminal a detached worker would otherwise inherit, so a
    traceback written on the way down would be lost. It lives under ``CRON_WORK_DIR``
    beside the other things the cron owns, and is named after the run so the log of the
    run you are looking at is the one you can find.
    """
    directory = Path(settings.CRON_WORK_DIR) / WORKER_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"run-{run.id}.log"


def spawn_worker(run: models.CronRun) -> models.CronRun:
    """Hand the run to a detached worker process and record its pid.

    ``runserver`` autoreloads, so a run done inside the Django process would be killed
    half-finished the next time a file is saved. The worker is therefore started in its
    own session, which detaches it from the web process's process group and lets it
    outlive the reload. It runs under the interpreter now serving the request so it sees
    the same virtualenv, and its pid is stored so a later pass can tell a live run from
    a stalled one.
    """
    log_path = worker_log_path(run)
    argv = [sys.executable, str(settings.BASE_DIR / "manage.py"), "run_cron", str(run.id)]
    with log_path.open("ab") as log:
        worker = processes.popen(argv, stdout=log, stderr=log, start_new_session=True)
    run.pid = worker.pid
    run.save(update_fields=["pid"])
    return run


# What each step of the pass needs from the environment (§2). A step whose settings
# are not all filled in cannot run, so it is skipped rather than half-done.
IMPORT_TICKETS = "import tickets from Linear"
WRITE_BRIEFS = "write ticket briefs"
IMPORT_PRS = "import pull requests from GitHub"
TRIAGE_PRS = "triage pull request comments"

# The state ``gh`` gives a pull request that is still in flight, lower-cased the way a
# ``PullRequest`` row stores it.
OPEN = "open"

STEP_SETTINGS = {
    IMPORT_TICKETS: ("LINEAR_API_KEY", "LINEAR_ASSIGNEE_EMAIL"),
    WRITE_BRIEFS: ("CLAUDE_BIN", "BRIEFS_DIR", "REPO_DIRS"),
    IMPORT_PRS: ("GITHUB_USER", "GITHUB_REPOS"),
    TRIAGE_PRS: ("GITHUB_USER", "REPO_DIRS", "CLAUDE_BIN", "CRON_WORK_DIR"),
}

# Linear grades urgency 1 (most urgent) to 4, with 0 meaning "nobody said".
PRIORITY_BY_LINEAR = {
    0: models.Priority.NONE,
    1: models.Priority.URGENT,
    2: models.Priority.HIGH,
    3: models.Priority.MEDIUM,
    4: models.Priority.LOW,
}


# A Linear issue URL spells its identifier out after ``/issue/``, e.g.
# https://linear.app/avantos/issue/CON-7/external-handoff-dispatch-drops-the-task-id
LINEAR_ISSUE_URL = re.compile(r"/issue/(?P<identifier>[A-Za-z][A-Za-z0-9]*-\d+)")


def identifier_in_url(url: str | None) -> str | None:
    """The Linear identifier a URL points at, upper-cased, or ``None``.

    People often raise the ticket here first and paste the Linear URL into it, leaving
    ``linear_identifier`` blank. The URL is then the only place the identifier is
    written down, so reading it back out is what lets the import recognise an issue it
    already has a ticket for.
    """
    match = LINEAR_ISSUE_URL.search(url or "")
    return match.group("identifier").upper() if match else None


def missing_settings(step: str) -> list[str]:
    """The names of the settings ``step`` needs that are blank."""
    return [name for name in STEP_SETTINGS[step] if not getattr(settings, name, None)]


def skip_step(run: models.CronRun, step: str, missing: list[str]) -> models.Alert:
    """Record why a step did not run.

    The cron runs unattended, so bad config must not raise and must never fall back to a
    guessed value — it leaves an alert naming the variables a human has to set.
    """
    return models.Alert.objects.create(
        kind=models.AlertKind.CRON_ERROR,
        cron_run=run,
        message=f"Skipped {step}: set {', '.join(missing)}.",
    )


def fail_step(run: models.CronRun, step: str, error: Exception) -> models.Alert:
    """Record that a step raised, so the rest of the pass can carry on.

    The cron runs unattended, so an outage at one source — Linear rejecting the key,
    say — must not cost the whole pass. The alert quotes the error rather than
    wording it ourselves, because the sender is the only one who knows what went
    wrong, and a human reading the alerts page needs that sentence to act on it.
    """
    return models.Alert.objects.create(
        kind=models.AlertKind.CRON_ERROR,
        cron_run=run,
        message=f"Failed {step}: {error}",
    )


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


def check_new_tickets(run: models.CronRun) -> list[models.Ticket]:
    """Import the Linear issues assigned to us as tickets.

    An import is a birth, not an edit: the ticket arrives already holding these values,
    so no ``field_change`` timeline entry is written for them. There is nobody to
    attribute such a change to, and a reader wants the issue's history from Linear, not
    a replay of the import.

    Only issues we have never seen before are born here. An issue a human already
    raised a ticket for by hand — recognised by the identifier they pasted in as a
    Linear URL — is adopted instead of duplicated: it gains the issue's ``linear_id``
    and ``linear_identifier``, and keeps everything the human wrote, which they may
    have worded that way on purpose. The cron runs every fifteen
    minutes over the same open issues, so an issue that already has a ticket is left
    untouched — not re-saved with identical values, which would move ``updated_at`` and
    make every pass look like a change.
    """
    client = linear.LinearClient(settings.LINEAR_API_KEY)
    issues = client.assigned_active_issues(settings.LINEAR_ASSIGNEE_EMAIL)

    known = set(models.Ticket.objects.values_list("linear_id", flat=True))
    unlinked = {}
    for ticket in models.Ticket.objects.filter(linear_id__isnull=True):
        identifier = ticket.linear_identifier or identifier_in_url(ticket.linear_url)
        if identifier:
            unlinked.setdefault(identifier.upper(), ticket)

    imported = []
    for issue in issues:
        if issue.id in known:
            continue
        adopted = unlinked.get(issue.identifier.upper())
        if adopted is not None:
            adopted.linear_id = issue.id
            adopted.linear_identifier = issue.identifier
            adopted.save(update_fields=["linear_id", "linear_identifier"])
            continue
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
        imported.append(ticket)
    return imported


def check_new_prs(run: models.CronRun) -> list[models.PullRequest]:
    """Import the open pull requests the configured user has in the watched repos.

    A pull request belongs to GitHub, not to this app, so the row is a cache: every
    pass overwrites what GitHub currently says about it, keyed by the identity GitHub
    itself uses, ``(repo, number)``. Nothing a human put on the row is touched, since
    the values written here are exactly the ones ``gh`` printed.

    Only the user's own open PRs are asked for. This app watches one person's work, and
    a repo that busy would otherwise answer with everybody's.
    """
    client = github.GhClient()
    seen = []
    for repo in settings.GITHUB_REPOS:
        still_open = []
        for pull_request in client.open_prs(repo, settings.GITHUB_USER):
            still_open.append(pull_request.number)
            row, _created = models.PullRequest.objects.update_or_create(
                repo=repo,
                number=pull_request.number,
                defaults={
                    "url": pull_request.url,
                    "title": pull_request.title,
                    "body": pull_request.body,
                    "branch": pull_request.branch,
                    "head_sha": pull_request.head_sha,
                    "state": pull_request.state,
                    "author": pull_request.author,
                },
            )
            # The conversation is read with the PR: what the reviewers asked for is
            # the reason this app watches pull requests at all.
            pull_requests.store_comments(client, row)
            seen.append(row)
        refresh_closed_prs(client, repo, still_open)
    pull_requests.link_to_tickets(seen)
    return seen


def refresh_closed_prs(client, repo: str, still_open: list[int]) -> list[models.PullRequest]:
    """Ask GitHub what became of the PRs that have left the open listing.

    A pull request does not vanish: a row we hold as ``open`` that the listing no longer
    answers with has been merged or closed, and the listing can never say so because it
    only returns what still matches it. So each one is asked about by name, and the state
    GitHub reports replaces the stale ``open`` — otherwise the row would claim the work is
    still in flight for as long as it exists.
    """
    gone = models.PullRequest.objects.filter(repo=repo, state=OPEN).exclude(
        number__in=still_open
    )
    refreshed = []
    for row in gone:
        row.state = client.pr(repo, row.number).state
        row.save(update_fields=["state"])
        refreshed.append(row)
    return refreshed


# What each step deals in, one row per step, for the line the header shows about a run.
STEP_NOUNS = {
    IMPORT_TICKETS: "ticket",
    WRITE_BRIEFS: "brief",
    IMPORT_PRS: "pull request",
    TRIAGE_PRS: "triage",
}

# Each step of the pass, in the order it runs.
STEPS = {
    IMPORT_TICKETS: check_new_tickets,
    # Briefs run after the import, so a ticket born in this pass is briefed in it too.
    WRITE_BRIEFS: briefs.write_briefs,
    # PRs come last: they are read against the tickets this pass already knows about.
    IMPORT_PRS: check_new_prs,
    # Triage runs on what the import just read, so a comment written since the last
    # pass is answered in the pass that first saw it.
    TRIAGE_PRS: triage.triage_pull_requests,
}


def counted(count: int, noun: str) -> str:
    """``count`` of ``noun``, worded the way a person would say it.

    The summary is read as a sentence, so "1 tickets" would read as a bug in this app
    rather than as a quiet pass.
    """
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def execute(run: models.CronRun) -> models.CronRun:
    """Do the run's work, then close it out.

    Each step is checked against its config first; an unconfigured step is skipped and
    the pass carries on, so one missing variable never costs the whole run. A step that
    raises is isolated the same way: the failure becomes an alert and the next step still
    gets its turn. The run itself is recorded either way, which is what makes a "nothing
    to do" cron distinguishable from one that never started.

    Each step that ran says how much it dealt with, and those counts become the run's
    ``summary`` — the one line the header shows for the last run, so it has to answer
    "what did that pass do?" without opening anything. A step that was skipped or that
    failed is left out of it: it dealt with nothing, and the alert it already wrote is
    where its reason belongs.
    """
    dealt_with = []
    for step, do_step in STEPS.items():
        missing = missing_settings(step)
        if missing:
            skip_step(run, step, missing)
            continue
        try:
            done = do_step(run)
        except Exception as error:  # any failure here belongs to this step, not the run
            fail_step(run, step, error)
        else:
            dealt_with.append(counted(len(done), STEP_NOUNS[step]))

    run.status = models.CronRunStatus.FINISHED
    run.summary = ", ".join(dealt_with)
    run.finished_at = timezone.now()
    run.save()
    return run
