"""The one place this app starts a headless Claude Code session.

Everything a run needs is described by a :class:`ClaudeRequest` and everything it
produced comes back as a :class:`ClaudeResult`, so the callers — briefs today, triage
later — never assemble argv or read stdout themselves. The process itself is started
through ``processes.run`` (PLAN crons §3, S3), which is what lets a test see the real
argv while no ``claude`` is started.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from tracker.integrations import processes


@dataclass(frozen=True)
class ClaudeRequest:
    """One headless run: what to ask, as whom, and where."""

    prompt: str
    cwd: str
    session_id: str
    model: str
    effort: str
    timeout: float | None = None


@dataclass(frozen=True)
class ClaudeResult:
    """What one headless run produced.

    ``claude -p --output-format json`` answers with a single JSON envelope. A run that
    dies, times out or is killed writes something else entirely, so parsing is lenient:
    an envelope we cannot read leaves ``raw`` empty rather than raising inside an
    unattended cron.
    """

    exit_code: int
    result_text: str = ""
    structured: Any = None
    raw: dict = field(default_factory=dict)
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class ClaudeRunner:
    """Runs headless Claude Code sessions with the configured executable."""

    def __init__(self, binary: str = "claude"):
        self._binary = binary

    def build_command(self, request: ClaudeRequest) -> list[str]:
        """The argv for one headless run.

        ``--session-id`` is ours, not Claude's: the caller already wrote the session row
        under that id, so the transcript this run leaves behind is the one the Sessions
        page offers to resume.
        """
        return [
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
        ]

    def run(self, request: ClaudeRequest) -> ClaudeResult:
        completed = processes.run(
            self.build_command(request),
            cwd=request.cwd,
            capture_output=True,
            text=True,
            timeout=request.timeout,
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
            raw=envelope,
            stderr=completed.stderr or "",
        )
