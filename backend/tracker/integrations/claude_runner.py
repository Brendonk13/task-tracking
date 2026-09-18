"""The one place this app starts a headless Claude Code session.

Everything a run needs is described by a :class:`ClaudeRequest` and everything it
produced comes back as a :class:`ClaudeResult`, so the callers — briefs today, triage
later — never assemble argv or read stdout themselves. The process itself is started
through ``processes.run`` (PLAN crons §3, S3), which is what lets a test see the real
argv while no ``claude`` is started.
"""

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from tracker.integrations import processes

NESTED_SESSION_VARIABLES = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")
"""The marks a Claude Code session leaves in the environment it hands to its children."""


def _child_environment() -> dict[str, str]:
    """This process's environment, minus the marks of the session that started us.

    The backend is itself usually started from a Claude Code session, and every child
    inherits that session's marks, so a headless ``claude`` we spawn would read them and
    take itself for a nested run. Only those names are dropped: the session still needs
    ``PATH``, ``HOME`` and the rest of the ambient environment to find its binary and its
    credentials, so starting from an empty environment would break every real run.
    """
    return {
        name: value
        for name, value in os.environ.items()
        if name not in NESTED_SESSION_VARIABLES
    }


def _as_text(output) -> str:
    """Whatever a killed process left on a stream, as a string.

    ``TimeoutExpired`` carries bytes or text depending on how the process was started,
    and carries nothing at all when it was killed before writing.
    """
    if output is None:
        return ""
    return output.decode(errors="replace") if isinstance(output, bytes) else str(output)


@dataclass(frozen=True)
class ClaudeRequest:
    """One headless run: what to ask, as whom, and where."""

    prompt: str
    cwd: str
    session_id: str
    model: str
    effort: str
    timeout: float | None = None
    permission_mode: str = ""
    add_dirs: tuple[str, ...] = ()
    json_schema: dict | None = None
    max_budget_usd: float | None = None
    allowed_tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    append_system_prompt: str = ""


@dataclass(frozen=True)
class ClaudeResult:
    """What one headless run produced.

    ``claude -p --output-format json`` answers with a single JSON envelope. A run that
    dies, times out or is killed writes something else entirely, so parsing is lenient:
    an envelope we cannot read leaves these fields empty rather than raising inside an
    unattended cron.
    """

    exit_code: int
    result_text: str = ""
    structured: Any = None
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


TIMEOUT_EXIT_CODE = 124
"""What ``timeout(1)`` reports for a process it had to kill; used for the same reason."""


class ClaudeRunner:
    """Runs headless Claude Code sessions with the configured executable."""

    def __init__(self, binary: str = "claude"):
        self._binary = binary

    def build_command(self, request: ClaudeRequest) -> list[str]:
        """The argv for one headless run.

        ``--session-id`` is ours, not Claude's: the caller already wrote the session row
        under that id, so the transcript this run leaves behind is the one the Sessions
        page offers to resume.

        Everything after it is what makes the run survivable unattended: no permission
        prompt can stop a cron, ``--json-schema`` makes the answer something the caller
        can read instead of prose, ``--add-dir`` grants the one directory outside ``cwd``
        the run must write to, and the budget is the ceiling on a run nobody is watching.

        Because no prompt can stop it, the allow and deny lists are the only thing
        standing between an unattended run and a write it can never take back, so both
        are passed the way the binary reads them: the flag once, then every tool as its
        own argv value. The appended system prompt states the same rule in words, for
        the model rather than for the permission layer.
        """
        command = [
            self._binary,
            "-p",
            request.prompt,
            "--output-format",
            "json",
            "--model",
            request.model,
            "--effort",
            request.effort,
            "--session-id",
            request.session_id,
            "--permission-prompts",
            "none",
        ]
        if request.permission_mode:
            command += ["--permission-mode", request.permission_mode]
        if request.allowed_tools:
            command += ["--allowedTools", *request.allowed_tools]
        if request.disallowed_tools:
            command += ["--disallowedTools", *request.disallowed_tools]
        if request.append_system_prompt:
            command += ["--append-system-prompt", request.append_system_prompt]
        if request.json_schema is not None:
            command += ["--json-schema", json.dumps(request.json_schema)]
        for directory in request.add_dirs:
            command += ["--add-dir", directory]
        if request.max_budget_usd is not None:
            command += ["--max-budget-usd", str(request.max_budget_usd)]
        return command

    def run(self, request: ClaudeRequest) -> ClaudeResult:
        """Run one headless session and describe how it went, however it ended.

        A session that never comes back is killed after ``request.timeout`` and reaches
        us as a ``TimeoutExpired`` instead of a result to parse. That is an outcome of
        the run, not a fault of the caller — an unattended cron cannot be stopped by one
        slow session — so it is answered as a ``ClaudeResult`` like any other, marked
        ``timed_out`` so the caller can say so in words.
        """
        try:
            completed = processes.run(
                self.build_command(request),
                cwd=request.cwd,
                env=_child_environment(),
                capture_output=True,
                text=True,
                timeout=request.timeout,
            )
        except subprocess.TimeoutExpired as expired:
            return ClaudeResult(
                exit_code=TIMEOUT_EXIT_CODE,
                stderr=_as_text(expired.stderr),
                timed_out=True,
            )
        return self._parse(completed)

    @staticmethod
    def _parse(completed) -> ClaudeResult:
        try:
            envelope = json.loads(completed.stdout or "")
        except ValueError:
            envelope = {}
        if not isinstance(envelope, dict):
            envelope = {}
        return ClaudeResult(
            exit_code=completed.returncode,
            result_text=envelope.get("result") or "",
            structured=envelope.get("structured_output"),
            stderr=completed.stderr or "",
        )
