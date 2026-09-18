import pytest

from tracker.tests.conftest import run_cron

pytestmark = pytest.mark.django_db


def test_run_cron_command_creates_a_finished_cron_run_listed_by_the_api(client, fake_processes):
    """A run with no config set still records one finished run (§4 C1.1).

    Nothing is configured, so every step is skipped, but the run itself is the
    thing under test: the command drives it (S2) and the API reports it (S1).
    """
    run = run_cron(client, trigger="command")

    assert client.get("/crons/runs").json() == [run]
    assert run["status"] == "finished"
    assert run["trigger"] == "command"
    assert run["finished_at"] is not None
