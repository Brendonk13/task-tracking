"""The one place this app talks to GitHub, through the ``gh`` CLI.

Read-only by design, the same way the Linear client is: every method here asks a
question, so no code path — not even a buggy one in an unattended cron — can comment
on, merge or close anything. ``gh`` is used rather than the REST API because it already
holds the user's credentials, so this app never handles a GitHub token.

The process is started through ``processes.run`` (PLAN crons §3, S3), which is what
lets a test see the real argv while no ``gh`` is started.
"""

import json
from dataclasses import dataclass

from tracker.integrations import processes

PR_FIELDS = (
    "number",
    "title",
    "url",
    "body",
    "headRefName",
    "headRefOid",
    "state",
    "author",
)
"""Every field a :class:`PullRequestSummary` is made of.

``gh`` prints only what ``--json`` names, so anything missing here is a column that
could never be filled — the list is the wire format of a PR row, not a preference.
"""


class GitHubError(RuntimeError):
    """``gh`` could not answer, or answered with something we cannot use."""


@dataclass(frozen=True)
class PullRequestSummary:
    """One pull request, flattened out of ``gh``'s JSON."""

    number: int
    title: str
    url: str
    body: str
    branch: str
    head_sha: str
    state: str
    author: str

    @classmethod
    def from_json(cls, item: dict) -> "PullRequestSummary":
        return cls(
            number=item["number"],
            title=item.get("title") or "",
            url=item.get("url") or "",
            # An empty PR description comes back as ``null``; our column is non-null.
            body=item.get("body") or "",
            branch=item.get("headRefName") or "",
            head_sha=item.get("headRefOid") or "",
            # ``gh`` shouts ``OPEN``/``MERGED``; the rest of this API speaks lower case.
            state=(item.get("state") or "").lower(),
            author=(item.get("author") or {}).get("login") or "",
        )


REVIEW_COMMENT = "review_comment"
ISSUE_COMMENT = "issue_comment"
REVIEW = "review"

COMMENT_FEEDS = (
    # Inline comments on the diff, threaded through ``in_reply_to_id``.
    (REVIEW_COMMENT, "pulls/{number}/comments"),
    # Comments on the PR as an issue, which is where the bots talk.
    (ISSUE_COMMENT, "issues/{number}/comments"),
    # The reviews themselves, whose body is the "here is what I think" note.
    (REVIEW, "pulls/{number}/reviews"),
)
"""The three places GitHub keeps the conversation on a pull request.

A triage that read only one of them would answer half the review, and the kinds are
stored alongside the id because the three feeds number their items separately: the same
id can name a review comment and a review. The values pair with
``models.PRCommentKind``.
"""


@dataclass(frozen=True)
class PRCommentPayload:
    """One thing somebody said on a pull request, flattened out of one of the feeds."""

    kind: str
    github_id: int
    in_reply_to_id: int | None
    author: str
    is_bot: bool
    body: str
    path: str
    line: int | None
    url: str

    @classmethod
    def from_json(cls, kind: str, item: dict) -> "PRCommentPayload":
        user = item.get("user") or {}
        return cls(
            kind=kind,
            github_id=item["id"],
            # Only an inline comment can be a reply; the other two feeds are flat.
            in_reply_to_id=item.get("in_reply_to_id"),
            author=user.get("login") or "",
            # GitHub says so itself, rather than us guessing from a ``[bot]`` suffix.
            is_bot=(user.get("type") or "") == "Bot",
            body=item.get("body") or "",
            # Only an inline comment hangs off a file, and a comment on an outdated
            # diff has lost its line.
            path=item.get("path") or "",
            line=item.get("line"),
            # The page a human opens to read it, not the API URL.
            url=item.get("html_url") or "",
        )


class GhClient:
    """A read-only ``gh`` client. Construct it with the executable to run."""

    def __init__(self, binary: str = "gh"):
        self._binary = binary

    def open_prs(self, repo: str, author: str) -> list[PullRequestSummary]:
        """The open pull requests ``author`` has in ``repo``.

        The narrowing is done by ``gh`` rather than by us: a busy repository answers
        with thousands of PRs, and filtering them here would mean paging all of them
        over the wire first only to throw nearly all of them away.
        """
        return [
            PullRequestSummary.from_json(item)
            for item in self._query(
                "pr",
                "list",
                "--repo",
                repo,
                "--author",
                author,
                "--state",
                "open",
                "--json",
                ",".join(PR_FIELDS),
            )
        ]

    def pr(self, repo: str, number: int) -> PullRequestSummary:
        """What GitHub currently says about one pull request in ``repo``.

        A listing only ever answers with the PRs that still match it, so a PR that has
        left ``--state open`` can only be asked about by name: this is how a row learns
        it was merged or closed instead of sitting at ``open`` forever.

        ``_query`` reads a silent ``gh`` as an empty listing, which is the right answer
        for a listing and no answer at all for one named PR, so the shape is checked
        here: a caller of this boundary is promised ``GitHubError`` when ``gh`` could
        not say anything usable, not a ``TypeError`` from unpacking a list as a PR.
        """
        answer = self._query(
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            ",".join(PR_FIELDS),
        )
        if not isinstance(answer, dict):
            raise GitHubError(f"gh did not describe pull request {number} in {repo}")
        return PullRequestSummary.from_json(answer)

    def comments(self, repo: str, number: int) -> list[PRCommentPayload]:
        """Everything said on one pull request, from all three of GitHub's feeds.

        Every feed is paginated, so every read is ``--paginate``: a plain ``gh api``
        stops at the first page and a busy PR would silently lose its review from the
        thirty-first comment on. The three answers become one list because the caller
        cares about the conversation, not about which endpoint carried each line.
        """
        return [
            PRCommentPayload.from_json(kind, item)
            for kind, path in COMMENT_FEEDS
            for item in self._query(
                "api",
                "--paginate",
                f"repos/{repo}/{path.format(number=number)}",
            )
        ]

    def _query(self, *arguments: str):
        """Run one ``gh`` question and parse what it printed.

        ``gh`` answers a listing with an array and a single ``pr view`` with an object,
        so the shape belongs to the caller that asked the question.

        ``gh`` reports trouble — a repo that is gone, an expired login — by exiting
        non-zero with a sentence on stderr, so that sentence is what the alert quotes:
        it is the only description of what went wrong that exists. A run that exited
        cleanly and printed nothing is the opposite: it is a listing with nothing in
        it, which is an ordinary answer and not worth waking anybody for.
        """
        completed = processes.run(
            [self._binary, *arguments],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            said = (completed.stderr or completed.stdout or "").strip()
            raise GitHubError(f"gh exited {completed.returncode}: {said}")
        printed = (completed.stdout or "").strip()
        if not printed:
            return []
        try:
            return json.loads(printed)
        except ValueError as error:
            raise GitHubError(f"gh printed something we cannot read: {error}") from error
