import json
import random

import httpx
import pytest
from django.core.management import call_command
from ninja.testing import TestClient

from tracker.api import api
from tracker.integrations import processes
from tracker.services import names
from tracker.tests.fakes import FakeProcesses, fixture_json

NAME_RNG_SEED = 4


@pytest.fixture
def client() -> TestClient:
    return TestClient(api)


@pytest.fixture
def seeded_names(monkeypatch) -> random.Random:
    """Make the session name generator deterministic (A11).

    Seed 4 is chosen because, against the current 40x40 word lists, it produces
    repeated adjective-animal pairs within 50 independent draws.
    """
    rng = random.Random(NAME_RNG_SEED)
    monkeypatch.setattr(names, "rng", rng)
    return rng


def register_session(
    client: TestClient,
    session_id: str = "a4c7e1b9-6f2d-4e83-b5a0-9d1c3f7e2b46",
    directory: str = "/home/me/proj",
) -> dict:
    """PUT a session through the API and return the response JSON."""
    response = client.put(f"/sessions/{session_id}", json={"directory": directory})
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def fake_processes(monkeypatch) -> FakeProcesses:
    """Swap the child-process boundary (S3). No real ``gh`` or ``claude`` is started."""
    fake = FakeProcesses()
    monkeypatch.setattr(processes, "run", fake.run)
    monkeypatch.setattr(processes, "popen", fake.popen)
    monkeypatch.setattr(processes, "pid_alive", fake.pid_alive)
    return fake


class LinearWire:
    """The Linear HTTP boundary (S3): canned pages, plus every request it saw.

    ``serve("linear/assigned_page1.json", "linear/assigned_page2.json")`` answers the
    first POST with page 1 and every later one with page 2 — the last response repeats
    so a step that queries twice does not run out.
    """

    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict] = []

    def serve(self, *fixture_names: str, status: int = 200) -> None:
        payloads = [fixture_json(name) for name in fixture_names]

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            self.bodies.append(json.loads(request.content))
            index = min(len(self.requests) - 1, len(payloads) - 1)
            return httpx.Response(status, json=payloads[index])

        self._install(httpx.MockTransport(handler))

    def fail(self, exception: Exception) -> None:
        """Make every request raise, e.g. ``httpx.ConnectError("boom")``."""

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            raise exception

        self._install(httpx.MockTransport(handler))

    def _install(self, transport: httpx.BaseTransport) -> None:
        # Imported here so this fixture file stays importable before the client exists.
        from tracker.integrations import linear

        self._monkeypatch.setattr(linear, "transport", transport)


@pytest.fixture
def linear_transport(monkeypatch) -> LinearWire:
    return LinearWire(monkeypatch)


@pytest.fixture
def cron_settings(settings, tmp_path):
    """Every crons setting (§2) pointed at this test's tmp_path. Ordinary config."""
    settings.LINEAR_API_KEY = "lin_api_test_key"
    settings.LINEAR_ASSIGNEE_EMAIL = "brendon.keirle@avantos.ai"
    settings.GITHUB_USER = "Brendonk13"
    settings.GITHUB_REPOS = ["mosaic-avantos/avantos"]
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(exist_ok=True)
    settings.REPO_DIRS = {"mosaic-avantos/avantos": str(repo_dir)}
    briefs = tmp_path / "briefs"
    briefs.mkdir(exist_ok=True)
    settings.BRIEFS_DIR = str(briefs)
    settings.CLAUDE_BIN = "claude"
    settings.CLAUDE_SESSION_TIMEOUT_SECONDS = 1800
    settings.CLAUDE_MAX_BUDGET_USD = 5
    settings.CRON_MAX_SESSIONS_PER_RUN = 3
    settings.CRON_WORK_DIR = str(tmp_path / "var")
    return settings


def run_cron(client: TestClient, *, trigger: str = "command") -> dict:
    """Run one whole cron run in-process (S2) and return its ``CronRun`` JSON."""
    call_command("run_cron", "--new", "--trigger", trigger)
    runs = client.get("/crons/runs").json()
    assert runs, "no cron run was recorded"
    return runs[0]
