"""Fakes for the two external boundaries: child processes and the Linear wire.

These live in the test package and are installed by ``monkeypatch`` (see conftest).
Production code never knows they exist.

Fixture provenance (``tracker/tests/fixtures``):

* ``gh/*.json`` — real, captured from ``mosaic-avantos/avantos`` with read-only ``gh``
  calls (``pr list`` on the open PRs, ``pr view`` on merged PR 10128, and the three
  comment endpoints of PR 9964), trimmed to a few items.
* ``claude/structured_output_probe.json`` and ``claude/triage_real_capture.json`` — real
  ``claude -p --output-format json --json-schema`` stdout. The probe fixes the key the
  structured object lands in (``structured_output``); the capture is one real
  ``/github-pr-comment-triage`` run against merged PR 10289.
* ``claude/triage_ok.json``, ``claude/triage_empty.json``, ``claude/ticket_brief_ok.json``
  — hand-authored in the captured envelope's shape, because the real capture had no
  code-change items and the brief skill needs a Linear connector this repo cannot enable.
* ``linear/*.json`` — hand-authored against Linear's GraphQL response shape; no
  ``LINEAR_API_KEY`` was configured when they were written. ``issue_not_found.json``
  follows the "Entity not found" error Linear documents for an ``issue(id:)`` that
  names nothing.
"""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    """Raw text of a captured fixture, e.g. ``fixture_text("gh/pr_list.json")``."""
    return (FIXTURES / name).read_text()


def fixture_json(name: str):
    """Parsed fixture, e.g. ``fixture_json("claude/triage_ok.json")``."""
    return json.loads(fixture_text(name))


def claude_result(structured=None, *, result: str = "done", session_id: str = "") -> str:
    """One ``claude -p --output-format json`` stdout line.

    Built from the shape the probe fixture recorded: the structured object lands in
    ``structured_output`` and its JSON text is repeated in ``result``.
    """
    payload = dict(fixture_json("claude/structured_output_probe.json"))
    payload["result"] = json.dumps(structured) if structured is not None else result
    if structured is not None:
        payload["structured_output"] = structured
    else:
        payload.pop("structured_output", None)
    if session_id:
        payload["session_id"] = session_id
    return json.dumps(payload)


@dataclass
class Call:
    """One recorded ``processes.run`` invocation."""

    argv: list[str]
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeout: float | None = None

    @property
    def program(self) -> str:
        return Path(self.argv[0]).name

    def arg_after(self, flag: str) -> str | None:
        """The value following ``flag``, or None when the flag is absent."""
        if flag not in self.argv:
            return None
        index = self.argv.index(flag)
        return self.argv[index + 1] if index + 1 < len(self.argv) else None

    def values_after(self, flag: str) -> list[str]:
        """Every value following ``flag`` up to the next ``--option``."""
        if flag not in self.argv:
            return []
        values = []
        for arg in self.argv[self.argv.index(flag) + 1:]:
            if arg.startswith("--"):
                break
            values.append(arg)
        return values


@dataclass
class Reply:
    match: Callable[[list[str]], bool]
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    timeout: bool = False
    side_effect: Callable[[Call], None] | None = None


@dataclass
class Popened:
    """What the fake ``popen`` hands back: just enough of a Popen for the caller."""

    argv: list[str]
    kwargs: dict
    pid: int

    def poll(self):
        return None


@dataclass
class FakeProcesses:
    """Stands in for ``tracker.integrations.processes``.

    Register canned answers with :meth:`on`; the most recently registered match wins,
    so a fixture-wide default can be overridden inside one test. Every call is
    recorded, so a test can assert on the argv the real tool would have seen.
    """

    calls: list[Call] = field(default_factory=list)
    popen_calls: list[Popened] = field(default_factory=list)
    replies: list[Reply] = field(default_factory=list)
    alive: Callable[[int], bool] = lambda pid: True
    next_pid: int = 4242

    # ---- setting up ----

    def on(self, *contains: str, **reply) -> None:
        """Answer calls whose argv contains every string in ``contains`` in order.

        ``on("gh", "pr", "list", stdout=...)`` matches ``gh pr list --repo ...``.
        """

        def match(argv: list[str]) -> bool:
            rest = list(argv)
            for needle in contains:
                if needle not in rest:
                    return False
                rest = rest[rest.index(needle) + 1:]
            return True

        self.replies.append(Reply(match=match, **reply))

    def on_fixture(self, *contains: str, name: str, **reply) -> None:
        """Answer with a captured fixture's raw text."""
        self.on(*contains, stdout=fixture_text(name), **reply)

    # ---- the boundary itself ----

    def run(self, argv, *, cwd=None, env=None, timeout=None, **kwargs):
        argv = [str(a) for a in argv]
        call = Call(argv=argv, cwd=None if cwd is None else str(cwd), env=env, timeout=timeout)
        self.calls.append(call)
        reply = self._reply_for(argv)
        if reply is None:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if reply.side_effect is not None:
            reply.side_effect(call)
        if reply.timeout:
            raise subprocess.TimeoutExpired(argv, timeout or 0)
        return subprocess.CompletedProcess(argv, reply.returncode, reply.stdout, reply.stderr)

    def popen(self, argv, **kwargs):
        argv = [str(a) for a in argv]
        self.next_pid += 1
        started = Popened(argv=argv, kwargs=kwargs, pid=self.next_pid)
        self.popen_calls.append(started)
        return started

    def pid_alive(self, pid: int) -> bool:
        return self.alive(pid)

    def _reply_for(self, argv: list[str]) -> Reply | None:
        for reply in reversed(self.replies):
            if reply.match(argv):
                return reply
        return None

    # ---- reading back what happened ----

    def calls_to(self, program: str) -> list[Call]:
        return [call for call in self.calls if call.program == program]

    def argvs_to(self, program: str) -> list[list[str]]:
        return [call.argv for call in self.calls_to(program)]
