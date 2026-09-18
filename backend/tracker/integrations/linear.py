"""The one place this app talks to Linear's GraphQL API.

Read-only by design: every method here is a query, so no code path — not even a buggy
one — can move, close or comment on an issue in Linear. The cron runs unattended, so
the blast radius of a mistake has to be bounded by the client, not by discipline.

``transport`` is the seam a test swaps (see PLAN crons §3, S3). It is read at call
time and handed to ``httpx.Client``, so our URL, headers, query and parsing all run
for real while no request leaves the machine. Production leaves it ``None``, which is
httpx's own default transport.
"""

from dataclasses import dataclass, field

import httpx

API_URL = "https://api.linear.app/graphql"

# Swapped by tests; ``None`` means "httpx, use your normal transport".
transport: httpx.BaseTransport | None = None

# One page of the issues assigned to a person and not yet finished. Completed and
# cancelled issues are dropped by Linear rather than by us, so the wire stays small.
ASSIGNED_ISSUES_QUERY = """
query AssignedIssues($email: String!, $after: String) {
  issues(
    first: 50
    after: $after
    filter: {
      assignee: { email: { eq: $email } }
      state: { type: { nin: ["completed", "canceled"] } }
    }
  ) {
    nodes {
      id
      identifier
      title
      description
      priority
      url
      branchName
      state { name type }
      project { name }
      labels { nodes { name } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


class LinearError(RuntimeError):
    """Linear could not be reached, or answered with something we cannot use."""


@dataclass(frozen=True)
class LinearIssue:
    """One issue, flattened out of the GraphQL node's nesting."""

    id: str
    identifier: str
    title: str
    description: str = ""
    priority: int = 0
    url: str = ""
    branch_name: str = ""
    state_name: str = ""
    state_type: str = ""
    project: str | None = None
    labels: list[str] = field(default_factory=list)

    @classmethod
    def from_node(cls, node: dict) -> "LinearIssue":
        state = node.get("state") or {}
        project = node.get("project") or {}
        labels = (node.get("labels") or {}).get("nodes") or []
        return cls(
            id=node["id"],
            identifier=node["identifier"],
            title=node["title"],
            # Linear sends ``null`` for an empty body; our column is a non-null string.
            description=node.get("description") or "",
            priority=node.get("priority") or 0,
            url=node.get("url") or "",
            branch_name=node.get("branchName") or "",
            state_name=state.get("name") or "",
            state_type=state.get("type") or "",
            project=project.get("name"),
            labels=[label["name"] for label in labels],
        )


class LinearClient:
    """A read-only Linear client. Construct it with the personal API key."""

    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None):
        self._api_key = api_key
        self._transport = transport

    def assigned_active_issues(self, email: str) -> list[LinearIssue]:
        """Every unfinished issue assigned to ``email``, across all pages.

        Linear answers one page at a time, so a caller that read only the first page
        would silently drop work. The cursor comes from the server's ``pageInfo``
        rather than from the last node, because paging is the server's opinion.

        A server that keeps saying ``hasNextPage`` while handing back the cursor we
        just sent would spin this loop forever inside an unattended cron. That page is
        the one we already have, so it is dropped and the walk ends there.
        """
        issues: list[LinearIssue] = []
        after: str | None = None
        while True:
            data = self._query(ASSIGNED_ISSUES_QUERY, {"email": email, "after": after})
            page = data["issues"]
            page_info = page.get("pageInfo") or {}
            cursor = page_info.get("endCursor")
            if after is not None and cursor == after:
                return issues

            issues.extend(LinearIssue.from_node(node) for node in page["nodes"])
            if not page_info.get("hasNextPage") or not cursor:
                return issues
            after = cursor

    def _query(self, query: str, variables: dict) -> dict:
        # The transport is looked up per call, never cached, so a test that swaps the
        # module attribute is obeyed by clients built before the swap.
        with httpx.Client(
            transport=self._transport or transport,
            # Linear personal keys go in ``Authorization`` raw: no ``Bearer`` prefix.
            headers={"Authorization": self._api_key, "Content-Type": "application/json"},
            timeout=30.0,
        ) as client:
            try:
                response = client.post(
                    API_URL, json={"query": query, "variables": variables}
                )
            except httpx.HTTPError as error:
                raise LinearError(f"Linear request failed: {error}") from error

        if response.status_code >= 400:
            raise LinearError(f"Linear returned HTTP {response.status_code}")
        payload = response.json()
        if payload.get("errors"):
            messages = "; ".join(e.get("message", "") for e in payload["errors"])
            raise LinearError(f"Linear returned errors: {messages}")
        return payload["data"]
