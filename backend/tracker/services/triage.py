"""PR comment triage: a headless ``/github-pr-comment-triage`` session per PR that owes
a reviewer an answer.

A review comment nobody has answered is work a human owes somebody else, and it is the
only reason this app watches pull requests at all. The cron hands each such PR to a
Claude Code session so the reading — which comment is right, what the code actually says
— is already done by the time a person sits down with the PR. The session runs in the
working copy configured for that PR's repository, because a triage reads the diff, and
the wrong checkout reads the wrong code.
"""

from django.conf import settings

from tracker import models
from tracker.integrations.claude_runner import ClaudeRequest, ClaudeRunner
from tracker.services import sessions

OPEN = "open"
"""The state of a pull request still in flight, as a ``PullRequest`` row stores it."""

TRIAGE_MODEL = "opus"
TRIAGE_EFFORT = "high"

TRIAGE_SKILL = "/github-pr-comment-triage"
"""The skill that does the reading; the session is only the thing that starts it."""


def triage_prompt(pull_request: models.PullRequest) -> str:
    """Point the skill at one pull request, the way its own interface reads.

    The skill takes the PR, its repository and the login whose unanswered comments are
    being looked for, because it talks to GitHub itself rather than being handed what
    this app already cached.
    """
    return (
        f"{TRIAGE_SKILL} --pr {pull_request.number} --repo {pull_request.repo} "
        f"--user {settings.GITHUB_USER}"
    )


def pending_comments(pull_request: models.PullRequest):
    """The comments on a PR that are still waiting on its author.

    Waiting means two things: nobody here has triaged it yet, so a pass over unchanged
    work starts nothing, and it was not written by the configured user — their own
    comments are the answers, not the questions.
    """
    return pull_request.comments.filter(triaged_at__isnull=True).exclude(
        author=settings.GITHUB_USER
    )


def pull_requests_needing_triage():
    """The open PRs that have a comment nobody has answered.

    Only open ones: a merged or closed PR's conversation is over, and triaging it would
    produce work on code that has already shipped.
    """
    return [
        pull_request
        for pull_request in models.PullRequest.objects.filter(state=OPEN)
        if pending_comments(pull_request).exists()
    ]


def triage_pull_requests(run: models.CronRun) -> list[models.Session]:
    """Start one triage session per pull request that owes a reviewer an answer.

    As with briefs, the session row is written before the process is started, so the
    sessions page never shows a ``claude`` running with nothing to explain it, and a
    crash still leaves the session behind to be found. The session is linked to the PR's
    ticket, because that is where the resulting work will land — a session that found
    its ticket only at the end could not be followed while it ran.

    A PR whose repository has no configured working copy is passed over rather than run
    somewhere guessed: a triage reads the diff, and there is no safe default checkout.
    """
    runner = ClaudeRunner(settings.CLAUDE_BIN)
    started = []
    for pull_request in pull_requests_needing_triage():
        directory = settings.REPO_DIRS.get(pull_request.repo)
        if not directory:
            continue
        session = sessions.create_managed_session(
            purpose=models.SessionPurpose.PR_TRIAGE,
            directory=directory,
            model=TRIAGE_MODEL,
            effort=TRIAGE_EFFORT,
            ticket=pull_request.ticket,
            cron_run=run,
        )
        runner.run(
            ClaudeRequest(
                prompt=triage_prompt(pull_request),
                cwd=directory,
                session_id=session.session_id,
                model=session.model,
                effort=session.effort,
                timeout=settings.CLAUDE_SESSION_TIMEOUT_SECONDS,
                max_budget_usd=settings.CLAUDE_MAX_BUDGET_USD,
            )
        )
        started.append(session)
    return started
