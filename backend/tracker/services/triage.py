"""PR comment triage: a headless ``/github-pr-comment-triage`` session per PR that owes
a reviewer an answer.

A review comment nobody has answered is work a human owes somebody else, and it is the
only reason this app watches pull requests at all. The cron hands each such PR to a
Claude Code session so the reading — which comment is right, what the code actually says
— is already done by the time a person sits down with the PR. The session runs in the
working copy configured for that PR's repository, because a triage reads the diff, and
the wrong checkout reads the wrong code.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from tracker import models
from tracker.integrations.claude_runner import ClaudeRequest, ClaudeResult, ClaudeRunner
from tracker.services import sessions
from tracker.services import tasks as task_service

OPEN = "open"
"""The state of a pull request still in flight, as a ``PullRequest`` row stores it."""

TRIAGE_MODEL = "opus"
TRIAGE_EFFORT = "high"

TRIAGE_SKILL = "/github-pr-comment-triage"
"""The skill that does the reading; the session is only the thing that starts it."""

TRIAGE_SCRATCH_DIR = "/tmp"
"""The skill's own scratch space: it renders its report through a script it writes
there."""

TRIAGE_DIR_NAME = "triage"
"""The folder under ``CRON_WORK_DIR`` that holds one analysis per triage run."""

TRIAGE_ALLOWED_TOOLS = (
    "Read",
    "Glob",
    "Grep",
    "Agent",
    "Skill",
    "Write",
    "Bash(python3:*)",
    "Bash(gh pr view:*)",
    "Bash(gh pr diff:*)",
    "Bash(gh repo view:*)",
    "Bash(gh api:*)",
    "Bash(git fetch:*)",
    "Bash(git show:*)",
    "Bash(git log:*)",
    "Bash(git diff:*)",
    "Bash(git rev-parse:*)",
    "Bash(rg:*)",
    "Bash(grep:*)",
    "Bash(ls:*)",
)
"""Everything a triage run is allowed to touch.

The job is to read: the pull request, the feeds behind it and the code it talks about.
``gh api`` is opened as a whole because the comment feeds are plain GETs against paths
this app does not enumerate, and the deny list below is what keeps it a read.
``git fetch`` and ``git show`` are here because the checkout is very likely parked on
another branch, so the PR's own code can only be read out of the fetched ref rather than
the working tree. ``Write`` stays, and only for the analysis JSON the run is asked for.
"""

TRIAGE_DISALLOWED_TOOLS = (
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "Bash(gh pr comment:*)",
    "Bash(gh pr review:*)",
    "Bash(gh pr merge:*)",
    "Bash(gh pr close:*)",
    "Bash(gh api -X:*)",
    "Bash(gh api --method:*)",
    "Bash(gh api graphql:*)",
    "Bash(gh api -f:*)",
    "Bash(gh api -F:*)",
    "Bash(gh api --input:*)",
    "Bash(git commit:*)",
    "Bash(git push:*)",
    "Bash(git checkout:*)",
    "Bash(git switch:*)",
    "Bash(git stash:*)",
    "Bash(git rebase:*)",
    "Bash(git reset:*)",
    "mcp__claude_ai_Linear__create_*",
    "mcp__claude_ai_Linear__update_*",
    "mcp__claude_ai_Linear__delete_*",
    "mcp__claude_ai_Linear__save_*",
)
"""Every way a triage run could answer a reviewer or disturb the checkout.

The run is unattended under ``--permission-prompts none``, which denies silently, so an
omission here is not a question to a human — it is permission. Two hazards are being
closed. Posting: the skill's whole subject is review comments, and a reply left on a PR
in the user's name cannot be recalled, so ``gh pr comment``/``review`` are shut and with
them the forms in which ``gh api`` stops being a read — a verb via ``-X``/``--method``, a
mutation in a ``graphql`` body, fields via ``-f``/``-F``/``--input``. The working tree:
the run may know exactly which line to change, but that change belongs in a task behind
the human gate, so it can neither edit the code it reads nor commit, push or move the
branch a person is standing on. The list is named rather than inlined so a reader can
audit it against §6 at a glance.
"""

TRIAGE_SYSTEM_PROMPT = (
    "Automated run from task-tracking. READ-ONLY on GitHub and Linear: never post a "
    "comment or a review, never create, update or archive anything. "
    "The checkout may not be on the PR branch: git fetch origin <branch> and read with "
    "git show origin/<branch>:<path> or gh pr diff. "
    "Never run a full test suite."
)
"""The same rules as the deny list, in words the model itself reads.

Tools are a fence, not an instruction, and a model that knows why the fence is there
stops walking into it. The two things the deny list cannot say are said here: which
commands to read the PR's code with, since a blocked ``git checkout`` otherwise reads as
a dead end rather than a redirection, and that a full test suite is not part of a
triage — it is not dangerous, only slow enough to burn the run's whole budget.
"""

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "pr": {
            "type": "object",
            "properties": {
                "number": {"type": "integer"},
                "title": {"type": "string"},
                "url": {"type": "string"},
                "headRefName": {"type": "string"},
                "headRefOid": {"type": "string"},
            },
            "required": ["number", "title", "url", "headRefName", "headRefOid"],
        },
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "url": {"type": "string"},
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "author": {"type": "string"},
                    "comment": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": [
                            "valid",
                            "partially-valid",
                            "invalid",
                            "needs-clarification",
                        ],
                    },
                    "needs_code_change": {"type": "boolean"},
                    "verdict_reason": {"type": "string"},
                    "background": {"type": "string"},
                    "plan": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "confidence_reason": {"type": "string"},
                    "suggested_comment": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "id",
                    "url",
                    "author",
                    "comment",
                    "verdict",
                    "needs_code_change",
                    "verdict_reason",
                    "plan",
                    "confidence",
                    "confidence_reason",
                ],
            },
        },
    },
    "required": ["pr", "summary", "items"],
}
"""The shape of one triage, as the report renderer already describes it.

Each item is a judgement about one comment, and what the cron does with it — a task per
code change, a single task holding the drafted replies — needs the verdict, whether
code has to change, the plan and the confidence on every one of them, so those are
required.
``suggested_comment`` is not: a comment answered by changing the code has no reply to
draft, and demanding one would only invite an invented answer.
"""


TITLE_MAX_LENGTH = models.Task._meta.get_field("title").max_length
"""Asked of the column rather than repeated, because a task title is built out of a
reviewer's prose, which has no length limit at all."""

SENTENCE_END = re.compile(r"(?<=[.!?])\s")
"""Where one sentence of a reason stops, so a title can carry only its first."""


@dataclass(frozen=True)
class TriageItem:
    """One judgement about one review comment.

    The fields are the ones the cron acts on, and everything else the skill reports is
    left in the analysis file: a task is made out of the comment, the verdict behind it,
    the plan and the confidence, and nothing here decides anything a human cannot check
    against the conversation the ``url`` points back at.
    """

    url: str = ""
    comment: str = ""
    verdict: str = ""
    verdict_reason: str = ""
    needs_code_change: bool = False
    plan: list[str] = field(default_factory=list)
    confidence: int | None = None
    confidence_reason: str = ""
    suggested_comment: str = ""
    path: str = ""
    line: int | None = None
    author: str = ""


@dataclass(frozen=True)
class TriageAnalysis:
    """What one triage run concluded about one pull request."""

    summary: str = ""
    items: list[TriageItem] = field(default_factory=list)

    @property
    def code_change_items(self) -> list[TriageItem]:
        """The judgements that call for a change to the code.

        The rest are answered in words rather than in code, which is a different piece
        of work; making a task out of one would put something on the ticket that nobody
        could ever do.
        """
        return [item for item in self.items if item.needs_code_change]


def parse_analysis(payload) -> TriageAnalysis | None:
    """Read one analysis object into something typed, or ``None`` if it is not one.

    The run is unattended, so the payload is whatever a model chose to emit: prose, a
    list, a half-filled object. Anything that is not an object with items is refused
    here, and every field is read defensively, so a malformed analysis produces no
    tasks rather than a task made of ``None``.
    """
    if not isinstance(payload, dict):
        return None
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return None
    fields = {f.name for f in TriageItem.__dataclass_fields__.values()}
    items = [
        TriageItem(**{key: value for key, value in item.items() if key in fields})
        for item in raw_items
        if isinstance(item, dict)
    ]
    return TriageAnalysis(summary=str(payload.get("summary") or ""), items=items)


def read_analysis(session: models.Session, result: ClaudeResult) -> TriageAnalysis | None:
    """What the run concluded, from whichever of its two answers survived.

    The prompt asks for the analysis twice on purpose (§5), because either copy can go
    missing on its own: a long run can end without an envelope to parse, and a run that
    answers in prose still leaves the file behind. The structured output is preferred
    only because it needs no disk; the file is read when it is absent or unusable.
    """
    analysis = parse_analysis(result.structured)
    if analysis is not None:
        return analysis
    try:
        written = json.loads(Path(analysis_path(session)).read_text())
    except (OSError, ValueError):
        return None
    return parse_analysis(written)


def gate_title(pull_request: models.PullRequest) -> str:
    """The name of the one task a human is meant to pick up first."""
    return f"Human review of PR comment triage for PR #{pull_request.number}"


def item_title(item: TriageItem) -> str:
    """Name one piece of work by where it is and why it is being asked for.

    The place comes first because that is what a person scanning a ticket recognises,
    and only the first sentence of the reason follows: the rest of the argument is in
    the description, and the column is finite where a reviewer's prose is not.
    """
    where = f"{item.path}:{item.line}" if item.path else item.author
    reason = SENTENCE_END.split(item.verdict_reason.strip(), 1)[0]
    return " - ".join(part for part in (where, reason) if part)[:TITLE_MAX_LENGTH]


def item_description(item: TriageItem) -> str:
    """Everything the gate — and later whoever does the work — has to decide on.

    That is the reviewer's own words rather than a paraphrase of them, the verdict with
    the confidence that was placed in it, every step of the plan (a plan missing its
    last step is a different plan), and the link back to the conversation this task came
    out of, which is the only way to check any of it.
    """
    lines = [f"> {line}" for line in (item.comment or "").splitlines() or ["> "]]
    confidence = "" if item.confidence is None else f" ({item.confidence}%)"
    lines += ["", f"Verdict: {item.verdict}{confidence}"]
    if item.verdict_reason:
        lines.append(item.verdict_reason)
    if item.confidence_reason:
        lines.append(f"Confidence: {item.confidence_reason}")
    if item.plan:
        lines += ["", "Plan:"] + [f"- {step}" for step in item.plan]
    lines += ["", item.url]
    return "\n".join(lines)


def create_tasks(
    pull_request: models.PullRequest,
    session: models.Session,
    analysis: TriageAnalysis,
) -> list[models.Task]:
    """Turn one analysis into work on the PR's ticket, behind a human gate.

    The analysis is an opinion written unattended, so none of it becomes work anybody
    may start until a person has agreed to it. The gate task is created first and
    depends on nothing, which is what makes it the only startable piece; everything
    derived from the analysis depends on it, and because ``blocked_by`` drops finished
    dependencies, marking the gate done is the single act that releases the batch.

    A PR with no ticket has nowhere to put any of this, so nothing is written at all
    rather than tasks nobody would find.
    """
    ticket = pull_request.ticket
    if ticket is None:
        return []
    gate = task_service.create(
        ticket,
        title=gate_title(pull_request),
        description=(
            f"Read the triage of PR #{pull_request.number} and decide which of the "
            f"tasks below are worth doing. Nothing on this ticket can start until this "
            f"task is done.\n\n{analysis.summary}"
        ),
    )
    created = [gate]
    for item in analysis.code_change_items:
        created.append(
            task_service.create(
                ticket,
                title=item_title(item),
                description=item_description(item),
                depends_on=[gate.id],
            )
        )
    for task in created:
        task_service.record(
            task,
            models.TaskHistoryKind.CREATED,
            session.session_id,
            f"{session.name} created this task from the triage of PR "
            f"#{pull_request.number}",
        )
    return created


def triage_dir() -> Path:
    """The directory triage analyses are written into, created if it is not there yet.

    It lives under ``CRON_WORK_DIR`` because the cron owns that place: the checkout is
    what the triage is reading and is forbidden to touch, and ``/tmp`` is where the
    skill falls back when it is given nowhere better, which no second reader can rely
    on.
    """
    directory = Path(settings.CRON_WORK_DIR) / TRIAGE_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def analysis_path(session: models.Session) -> str:
    """Where one run is asked to leave its analysis.

    The file is named after the session rather than the pull request, so a later triage
    of the same PR can never be handed the previous run's findings, and the file that is
    read back is provably the one this run was told to write.
    """
    return str(triage_dir() / f"{session.session_id}.json")


def triage_prompt(pull_request: models.PullRequest, path: str) -> str:
    """Point the skill at one pull request, the way its own interface reads.

    The skill takes the PR, its repository and the login whose unanswered comments are
    being looked for, because it talks to GitHub itself rather than being handed what
    this app already cached.

    The analysis is then asked for twice — as a file at ``path`` and as the structured
    output — because either one alone can go missing: a long run may end without an
    envelope to parse, and a run that answers in prose still leaves the file behind. The
    ban on posting is repeated here in words the model reads, even though the deny list
    already enforces it, because the skill is capable of replying on GitHub by itself.
    """
    return (
        f"{TRIAGE_SKILL} --pr {pull_request.number} --repo {pull_request.repo} "
        f"--user {settings.GITHUB_USER}\n"
        f"Regardless of item count, write the full analysis JSON "
        f"(render_report.py input schema) to {path} and return the same object as your "
        f"structured output. Do not post anything."
    )


def thread_root(comment: models.PRComment, by_github_id: dict[int, models.PRComment]):
    """The comment that started the review thread ``comment`` belongs to.

    A reply carries the id of the comment it answers, so the thread is walked upwards
    until a comment answers nothing — that one is the root. A comment from a flat feed,
    which never answers anything, is the root of a thread of one.
    """
    seen = set()
    while comment.in_reply_to_id is not None and comment.github_id not in seen:
        seen.add(comment.github_id)
        parent = by_github_id.get(comment.in_reply_to_id)
        if parent is None:
            break
        comment = parent
    return comment


def pending_comments(pull_request: models.PullRequest) -> list[models.PRComment]:
    """The comments on a PR that are still waiting on its author.

    Waiting means three things. Nobody here has triaged it yet, so a pass over unchanged
    work starts nothing. It was not written by the configured user — their own comments
    are the answers, not the questions. And the thread it hangs in does not end in one
    of the user's comments: once he has replied, the reviewer's comment is settled, and
    answering somebody never deletes what they wrote, so a rule that only counted other
    people's comments would keep triaging the same conversation forever.
    """
    comments = list(pull_request.comments.all())
    by_github_id = {comment.github_id: comment for comment in comments}
    last_in_thread: dict[int, models.PRComment] = {}
    for comment in comments:
        last_in_thread[thread_root(comment, by_github_id).github_id] = comment
    return [
        comment
        for comment in comments
        if comment.triaged_at is None
        and comment.author != settings.GITHUB_USER
        and last_in_thread[thread_root(comment, by_github_id).github_id].author
        != settings.GITHUB_USER
    ]


def pull_requests_needing_triage():
    """The open PRs that have a comment nobody has answered.

    Only open ones: a merged or closed PR's conversation is over, and triaging it would
    produce work on code that has already shipped.
    """
    return [
        pull_request
        for pull_request in models.PullRequest.objects.filter(state=OPEN)
        if pending_comments(pull_request)
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
        result = runner.run(
            ClaudeRequest(
                prompt=triage_prompt(pull_request, analysis_path(session)),
                cwd=directory,
                session_id=session.session_id,
                model=session.model,
                effort=session.effort,
                timeout=settings.CLAUDE_SESSION_TIMEOUT_SECONDS,
                add_dirs=(str(triage_dir()), TRIAGE_SCRATCH_DIR),
                json_schema=TRIAGE_SCHEMA,
                allowed_tools=TRIAGE_ALLOWED_TOOLS,
                disallowed_tools=TRIAGE_DISALLOWED_TOOLS,
                append_system_prompt=TRIAGE_SYSTEM_PROMPT,
                max_budget_usd=settings.CLAUDE_MAX_BUDGET_USD,
            )
        )
        analysis = read_analysis(session, result)
        if analysis is not None:
            create_tasks(pull_request, session, analysis)
        started.append(session)
    return started
