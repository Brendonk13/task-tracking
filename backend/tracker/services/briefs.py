"""Ticket briefs: a headless ``/ticket-brief`` session per imported ticket.

A ticket that arrives from Linear is a wall of text nobody has read yet. The cron hands
each new one to a Claude Code session so that, by the time a human opens it, the
background work is already done. The session runs in the repository the brief is
written about, because the skill reads that code.
"""

from django.conf import settings

from tracker import models
from tracker.integrations.claude_runner import ClaudeRequest, ClaudeRunner
from tracker.services import sessions

BRIEF_MODEL = "opus"
BRIEF_EFFORT = "high"


def brief_prompt(ticket: models.Ticket) -> str:
    """Ask the skill for the brief, by the identifier a person would name it with."""
    return (
        f"/ticket-brief {ticket.linear_identifier}\n"
        f"Write the brief into {settings.BRIEFS_DIR} (default naming)."
    )


def repo_directory() -> str:
    """Where a brief session runs: the checkout briefs are written from."""
    return next(iter(settings.REPO_DIRS.values()))


def tickets_needing_brief():
    """Tickets from Linear that no brief session has ever been started for.

    The cron passes over the same open issues every fifteen minutes, so "needs a brief"
    has to mean "was never handed to a session", not "has no brief yet" — otherwise a
    still-running session would be started again on the next pass.
    """
    return models.Ticket.objects.filter(linear_identifier__isnull=False).exclude(
        sessions__purpose=models.SessionPurpose.TICKET_BRIEF
    )


def write_briefs(run: models.CronRun) -> list[models.Session]:
    """Start one brief session per ticket that needs one.

    The session row is written before the process is started, so the process is never
    the only record that it exists.
    """
    runner = ClaudeRunner(settings.CLAUDE_BIN)
    directory = repo_directory()
    started = []
    for ticket in tickets_needing_brief():
        session = sessions.create_managed_session(
            purpose=models.SessionPurpose.TICKET_BRIEF,
            directory=directory,
            model=BRIEF_MODEL,
            effort=BRIEF_EFFORT,
            ticket=ticket,
            cron_run=run,
        )
        runner.run(
            ClaudeRequest(
                prompt=brief_prompt(ticket),
                cwd=directory,
                session_id=session.session_id,
                model=session.model,
                effort=session.effort,
                timeout=settings.CLAUDE_SESSION_TIMEOUT_SECONDS,
            )
        )
        started.append(session)
    return started
