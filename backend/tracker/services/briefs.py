"""Ticket briefs: a headless ``/ticket-brief`` session per imported ticket.

A ticket that arrives from Linear is a wall of text nobody has read yet. The cron hands
each new one to a Claude Code session so that, by the time a human opens it, the
background work is already done. The session runs in the repository the brief is
written about, because the skill reads that code.
"""

from pathlib import Path

from django.conf import settings

from tracker import models
from tracker.integrations.claude_runner import ClaudeRequest, ClaudeResult, ClaudeRunner
from tracker.services import sessions

BRIEF_MODEL = "opus"
BRIEF_EFFORT = "high"
BRIEF_PERMISSION_MODE = "acceptEdits"

BRIEF_ALLOWED_TOOLS = (
    "Read",
    "Glob",
    "Grep",
    "Agent",
    "Skill",
    "Write",
    "Edit",
    "WebFetch",
    "Bash(python3:*)",
    "Bash(git log:*)",
    "Bash(git show:*)",
    "Bash(git diff:*)",
    "Bash(ls:*)",
    "Bash(rg:*)",
    "Bash(grep:*)",
    "mcp__claude_ai_Linear__get_*",
    "mcp__claude_ai_Linear__list_*",
    "mcp__claude_ai_Linear__search_*",
    "mcp__claude_ai_Linear__extract_images",
)
"""Everything a brief run is allowed to touch.

Reading the ticket and the code it names is the whole job, so the list is the reading
tools plus Linear's query side; ``Write``/``Edit`` are here because the brief itself is
two files, and the deny list and the system prompt are what keep them pointed at the
briefs directory.
"""

BRIEF_DISALLOWED_TOOLS = (
    "mcp__claude_ai_Linear__create_*",
    "mcp__claude_ai_Linear__update_*",
    "mcp__claude_ai_Linear__delete_*",
    "mcp__claude_ai_Linear__save_*",
    "mcp__claude_ai_Linear__add_*",
    "mcp__claude_ai_Linear__archive_*",
    "Bash(git commit:*)",
    "Bash(git push:*)",
    "Bash(git checkout:*)",
    "Bash(gh pr comment:*)",
    "Bash(gh pr review:*)",
    "Bash(gh api -X:*)",
)
"""Every way a brief run could change something outside itself.

``--permission-prompts none`` denies silently, so nothing here would ever surface as a
question to a human — an omission would simply be allowed. The list is therefore named
rather than inlined, so that a reader can audit it against §6 at a glance.
"""

BRIEF_SYSTEM_PROMPT = (
    "Automated run from task-tracking. READ-ONLY on Linear, GitHub and Slack: "
    "never create, update, comment on, or archive anything. "
    "Write only under {briefs_dir}. Never write inside the repository."
)
"""The same rule as the deny list, in words the model itself reads."""

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "md_path": {"type": "string"},
        "html_path": {"type": "string"},
        "next_step": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["md_path", "html_path", "next_step", "summary"],
}
"""What the run has to hand back.

The brief itself is two files on disk, so the only thing the cron needs from the
process is where they landed — plus enough of the verdict to show on the ticket
without opening the HTML.
"""


def brief_prompt(ticket: models.Ticket) -> str:
    """Ask the skill for the brief, by the identifier a person would name it with."""
    return (
        f"/ticket-brief {ticket.linear_identifier}\n"
        f"Write the brief into {settings.BRIEFS_DIR} (default naming)."
    )


def brief_system_prompt() -> str:
    """The read-only rule, naming the one directory this run may write to."""
    return BRIEF_SYSTEM_PROMPT.format(briefs_dir=settings.BRIEFS_DIR)


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


def brief_files_on_disk(
    ticket: models.Ticket, session: models.Session
) -> tuple[str, str] | None:
    """Find the brief this run left behind when it never said where it put it.

    The skill names a brief ``<date>-<identifier>.html`` with the ``.md`` beside it, so
    the directory listing is a second source for the paths — the artefact is the point
    of the run, and losing it because the model went quiet would be the tracker's fault
    rather than the session's. Only files written since the session row was created
    count, so a brief left by an earlier run about the same ticket is never claimed as
    this run's work, and the newest match wins because the run may have rewritten it.
    """
    briefs_dir = Path(settings.BRIEFS_DIR)
    if not briefs_dir.is_dir():
        return None
    started = session.created_at.timestamp()
    candidates = []
    for html in briefs_dir.glob(f"*-{ticket.linear_identifier}.html"):
        md = html.with_suffix(".md")
        if not md.is_file() or html.stat().st_mtime < started:
            continue
        candidates.append((html.stat().st_mtime, md, html))
    if not candidates:
        return None
    _mtime, md, html = max(candidates)
    return str(md), str(html)


def store_brief(
    ticket: models.Ticket, session: models.Session, structured
) -> models.TicketBrief | None:
    """Record where the run says it wrote the brief, so the ticket page can open it.

    The paths are taken from the structured output first, because the skill is the only
    thing that knows what it actually wrote; a run that stays silent is fallen back on
    the naming convention instead. A ticket keeps one brief, so a later run about the
    same ticket replaces the paths instead of leaving a reader to choose between two.
    """
    structured = structured if isinstance(structured, dict) else {}
    md_path = structured.get("md_path")
    html_path = structured.get("html_path")
    if not md_path or not html_path:
        found = brief_files_on_disk(ticket, session)
        if found is None:
            return None
        md_path, html_path = found
    brief, _created = models.TicketBrief.objects.update_or_create(
        ticket=ticket,
        defaults={"md_path": md_path, "html_path": html_path, "session": session},
    )
    return brief


def record_failure(
    ticket: models.Ticket, session: models.Session, result: ClaudeResult
) -> models.Alert:
    """Close out a dead brief run and tell a human about it.

    Nothing is stored about the brief: a run that died may have written half a file, and
    half a brief on the ticket page is worse than none. Closing the session and raising
    the alert is what every dead managed run does, so ``sessions.record_failure`` does
    it; what is this step's own is the wording — a human reading the alerts page has to
    see which ticket's brief was lost — and the ticket the alert is filterable by.
    """
    return sessions.record_failure(
        session,
        result,
        ticket=ticket,
        message=(
            f"Brief for {ticket.linear_identifier} failed: "
            f"{sessions.failure_reason(result)}"
        ),
    )


def record_brief(
    ticket: models.Ticket, session: models.Session, result: ClaudeResult
) -> models.TicketBrief | None:
    """Write down what one finished run produced: its brief, and its own closing state.

    A run that did not end cleanly produced nothing to write down, so it is recorded as
    a failure instead — and only as a failure, never as both.
    """
    if not result.ok:
        record_failure(ticket, session, result)
        return None
    structured = result.structured if isinstance(result.structured, dict) else {}
    brief = store_brief(ticket, session, structured)
    sessions.finish_session(
        session,
        last_message=result.result_text,
        summary=structured.get("summary", ""),
    )
    return brief


def write_briefs(run: models.CronRun) -> list[models.Session]:
    """Start one brief session per ticket that needs one, and record what it produced.

    The session row is written before the process is started, so the process is never
    the only record that it exists, and it is closed out as soon as that process is
    done — a session left reading ``running`` after its process died would be a lie to
    whoever is watching the sessions page.

    Only as many sessions are started as the run's remaining budget allows; the tickets
    that do not fit simply wait, because ``tickets_needing_brief`` will still offer them
    on the next pass. The work is deferred, never dropped.
    """
    runner = ClaudeRunner(settings.CLAUDE_BIN)
    directory = repo_directory()
    started = []
    for ticket in tickets_needing_brief():
        if sessions.remaining_session_budget(run) <= 0:
            break
        session = sessions.create_managed_session(
            purpose=models.SessionPurpose.TICKET_BRIEF,
            directory=directory,
            model=BRIEF_MODEL,
            effort=BRIEF_EFFORT,
            ticket=ticket,
            cron_run=run,
        )
        result = runner.run(
            ClaudeRequest(
                prompt=brief_prompt(ticket),
                cwd=directory,
                session_id=session.session_id,
                model=session.model,
                effort=session.effort,
                timeout=settings.CLAUDE_SESSION_TIMEOUT_SECONDS,
                permission_mode=BRIEF_PERMISSION_MODE,
                add_dirs=(settings.BRIEFS_DIR,),
                json_schema=BRIEF_SCHEMA,
                allowed_tools=BRIEF_ALLOWED_TOOLS,
                disallowed_tools=BRIEF_DISALLOWED_TOOLS,
                append_system_prompt=brief_system_prompt(),
                max_budget_usd=settings.CLAUDE_MAX_BUDGET_USD,
            )
        )
        record_brief(ticket, session, result)
        started.append(session)
    return started
