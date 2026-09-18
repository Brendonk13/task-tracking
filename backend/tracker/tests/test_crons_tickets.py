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


def test_assigned_linear_issues_become_tickets_with_identifier_priority_url_project_and_labels(
    client, cron_settings, fake_processes, linear_transport
):
    """Each assigned active Linear issue is imported as a ticket (§4 C1.3).

    The expected values are the ones written in ``linear/assigned_page1.json``,
    spelled out per issue rather than derived the way the import does it. Importing
    a ticket is a creation, so nothing about it reads as a series of edits: the new
    ticket's timeline holds no ``field_change`` entry.
    """
    linear_transport.serve("linear/assigned_page1.json")

    run_cron(client)

    tickets = {t["linear_identifier"]: t for t in client.get("/tickets").json()}
    assert sorted(tickets) == ["CON-7", "CON-8"]

    con7 = tickets["CON-7"]
    assert con7["title"] == "External handoff dispatch drops the task id"
    assert con7["priority"] == "urgent"
    assert con7["linear_url"] == (
        "https://linear.app/avantos/issue/CON-7/external-handoff-dispatch-drops-the-task-id"
    )
    assert con7["project"] == "Action Platform"
    assert con7["labels"] == ["backend", "bug"]

    con8 = tickets["CON-8"]
    assert con8["title"] == "Document the SAML assertion signing keys"
    assert con8["priority"] == "none"
    assert con8["linear_url"] == (
        "https://linear.app/avantos/issue/CON-8/document-the-saml-assertion-signing-keys"
    )
    assert con8["project"] is None
    assert con8["labels"] == []

    detail = client.get(f"/tickets/{con7['id']}").json()
    assert [e for e in detail["timeline"] if e["kind"] == "field_change"] == []
