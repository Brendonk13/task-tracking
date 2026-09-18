"""The one place that knows what a Linear identifier looks like.

An identifier (``CON-2386``) is written in two places this app reads: inside a Linear
URL, after ``/issue/``, and loose in prose — a branch name, a PR title, a sentence in a
body. Both readings are the same domain vocabulary, so they live together: the import
recognises a hand-raised ticket by the URL somebody pasted into it, and the PR matcher
recognises the same ticket by the identifier somebody typed into a branch. Keeping them
apart cost a shape written twice and an import cycle between ``crons`` and
``pull_requests``, neither of which owns the vocabulary they were both spelling out.

Every reading upper-cases what it found, so nothing downstream ever compares case:
GitHub lower-cases the identifier in a branch name and shouts it in a title.
"""

import re

IDENTIFIER = r"[A-Za-z][A-Za-z0-9]*-\d+"
"""A Linear identifier: a team key, a dash, a number."""

IN_PROSE = re.compile(IDENTIFIER)
"""The identifier loose in text, where there is no ``/issue/`` to anchor it."""

IN_URL = re.compile(rf"/issue/(?P<identifier>{IDENTIFIER})")
"""The identifier a Linear issue URL spells out, e.g.
https://linear.app/avantos/issue/CON-7/external-handoff-dispatch-drops-the-task-id"""


def identifier_in_url(url: str | None) -> str | None:
    """The Linear identifier a URL points at, upper-cased, or ``None``.

    People often raise the ticket here first and paste the Linear URL into it, leaving
    ``linear_identifier`` blank. The URL is then the only place the identifier is
    written down, so reading it back out is what lets the import recognise an issue it
    already has a ticket for.
    """
    match = IN_URL.search(url or "")
    return match.group("identifier").upper() if match else None


def identifiers_in(text: str | None) -> list[str]:
    """Every Linear identifier ``text`` spells, upper-cased, in the order written."""
    return [match.group(0).upper() for match in IN_PROSE.finditer(text or "")]
