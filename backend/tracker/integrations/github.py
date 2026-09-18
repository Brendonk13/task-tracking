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

    def _query(self, *arguments: str) -> list:
        """Run one ``gh`` listing and parse the items it printed.

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
