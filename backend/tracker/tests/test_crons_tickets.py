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


def test_run_without_linear_api_key_raises_a_cron_error_alert_naming_the_variable(
    client, cron_settings, fake_processes
):
    """Missing config skips the step and says which variable is missing (§2, §4 C1.2).

    Everything else is configured, so the only reason to skip the ticket import is
    the blank key — and the run itself must still finish.
    """
    cron_settings.LINEAR_API_KEY = ""

    run = run_cron(client, trigger="command")

    alerts = client.get("/alerts").json()
    assert len(alerts) == 1, alerts
    assert alerts[0]["kind"] == "cron_error"
    assert "LINEAR_API_KEY" in alerts[0]["message"]
    assert run["status"] == "finished"
