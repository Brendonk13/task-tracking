import re
import sys

import httpx
import pytest
from django.core.management import call_command

from tracker.tests import fakes
from tracker.tests.conftest import run_cron

pytestmark = pytest.mark.django_db


def test_post_crons_run_starts_a_run_and_launches_a_detached_worker(
    client, cron_settings, fake_processes
):
    """The web request records the run; a detached worker does the work (§4 C5.1).

    ``runserver`` autoreloads, so a run done inside the Django process would be killed
    half-finished the next time a file is saved. The endpoint therefore answers 202
    with a run that is already ``running``, and the only thing it starts is one
    process at the ``popen`` boundary (S3): this project's ``manage.py run_cron <id>``
    under the interpreter now serving the request, in its own session so it outlives
    the reload. ``GET /crons/summary`` is how the frontend sees that a run is in
    flight.
    """
    response = client.post("/crons/run")

    assert response.status_code == 202, response.content
    run = response.json()
    assert run["status"] == "running"
    assert run["trigger"] == "api"

    assert len(fake_processes.popen_calls) == 1, fake_processes.popen_calls
    worker = fake_processes.popen_calls[0]
    manage_py = str(cron_settings.BASE_DIR / "manage.py")
    assert worker.argv == [sys.executable, manage_py, "run_cron", str(run["id"])]
    assert worker.kwargs.get("start_new_session") is True

    assert client.get("/crons/summary").json()["running"] is True


def test_second_post_while_running_returns_the_same_run_with_200_and_launches_nothing(
    client, cron_settings, fake_processes
):
    """One cron run at a time; a second POST joins it rather than failing (§4 C5.2).

    Two triggers can fire at once — a system cron line and the frontend button — and a
    second run would import the same tickets and spawn the same sessions twice. A
    caller that arrives while one is in flight is not doing anything wrong, so it is
    told 200 with the run already going (202 is reserved for "I started one"), and
    nothing new appears at the ``popen`` boundary (S3).
    """
    first = client.post("/crons/run")
    assert first.status_code == 202, first.content

    second = client.post("/crons/run")

    assert second.status_code == 200, second.content
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "running"

    assert len(fake_processes.popen_calls) == 1, fake_processes.popen_calls
    assert len(client.get("/crons/runs").json()) == 1


def test_run_whose_worker_process_is_gone_is_marked_failed_and_a_new_run_can_start(
    client, cron_settings, fake_processes
):
    """A worker can die without ever closing its run (§4 C5.3).

    The machine reboots, the process is killed, the laptop lid closes mid-run: nothing
    gets the chance to write ``finished`` or ``failed``, so the row stays ``running``
    for ever and single flight (C5.2) then refuses every later trigger — crons are dead
    until someone edits the database. So the next POST asks the one question that can be
    answered from outside the worker, at the ``pid_alive`` boundary (S3): is the process
    that was going to do this run still there? When it is not, that run is closed as
    ``failed``, an operator-visible ``cron_error`` says which run was abandoned, and the
    caller gets the fresh run it asked for — 202, a new id, its own worker.
    """
    abandoned = client.post("/crons/run")
    assert abandoned.status_code == 202, abandoned.content
    assert abandoned.json()["pid"] == fake_processes.popen_calls[0].pid

    fake_processes.alive = lambda pid: False

    started = client.post("/crons/run")

    assert started.status_code == 202, started.content
    assert started.json()["status"] == "running"
    assert started.json()["id"] != abandoned.json()["id"]

    runs = {run["id"]: run for run in client.get("/crons/runs").json()}
    assert runs[abandoned.json()["id"]]["status"] == "failed", runs
    assert runs[started.json()["id"]]["status"] == "running", runs

    alerts = [
        alert
        for alert in client.get("/alerts").json()
        if alert["kind"] == "cron_error"
        and alert["cron_run_id"] == abandoned.json()["id"]
    ]
    assert len(alerts) == 1, client.get("/alerts").json()


def test_run_cron_command_with_an_existing_id_executes_that_run(
    client, cron_settings, fake_processes, linear_transport
):
    """The worker finishes the run the endpoint already recorded (§4 C5.4, §5).

    ``POST /crons/run`` and the worker are two halves of one pass: the request records
    the row and answers 202 with its id (C5.1), and the detached ``manage.py run_cron
    <id>`` is handed that id precisely so it does *that* run. A worker that started a
    run of its own instead would leave the recorded row ``running`` for ever — single
    flight (C5.2) would then refuse every later trigger until the stale reaper (C5.3)
    killed it — and the frontend, which follows the id it was given, would watch a run
    that nobody was doing. So afterwards there is still exactly one run, the one the
    API handed out, and it is ``finished``.

    The command's other mode (``--new``) is what every other lane uses; here the id is
    the whole point, so the run is given real work to report: the Linear pages import
    tickets and the ``gh pr list`` capture imports pull requests, and ``claude`` is
    answered harmlessly because briefs are C2's subject, not this one. ``summary`` is
    the one line the header shows for the last run, so it has to say what the pass did
    — how many tickets and how many pull requests it dealt with — and the counts are
    read back from the API rather than written down here.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")
    fake_processes.on("claude", stdout=fakes.claude_result(result="brief skipped"))
    fake_processes.on_fixture("gh", "pr", "list", name="gh/pr_list.json")

    response = client.post("/crons/run")
    assert response.status_code == 202, response.content
    run_id = response.json()["id"]

    call_command("run_cron", str(run_id))

    runs = client.get("/crons/runs").json()
    assert [run["id"] for run in runs] == [run_id], runs
    run = runs[0]
    assert run["status"] == "finished", run
    assert run["trigger"] == "api", run
    assert run["finished_at"] is not None, run

    tickets = len(client.get("/tickets").json())
    pull_requests = len(client.get("/pull-requests").json())
    assert tickets and pull_requests, (tickets, pull_requests)
    assert re.search(rf"\b{tickets}\b[^.]*\btickets?\b", run["summary"], re.IGNORECASE), run
    assert re.search(
        rf"\b{pull_requests}\b[^.]*\b(pull requests?|PRs?)\b", run["summary"], re.IGNORECASE
    ), run


def unreachable_linear(cron_settings, linear_transport) -> None:
    """The Linear host cannot be reached at all: every request raises."""
    linear_transport.fail(httpx.ConnectError("connection refused"))


def missing_repo_checkout(cron_settings, linear_transport) -> None:
    """Linear works, so tickets arrive, but the configured checkout is not there."""
    linear_transport.serve("linear/assigned_page1.json")
    cron_settings.REPO_DIRS = {"mosaic-avantos/avantos": "/nonexistent/checkout"}


@pytest.mark.parametrize(
    ("break_a_step", "expected_in_message"),
    [
        pytest.param(unreachable_linear, "connection refused", id="linear_unreachable"),
        pytest.param(missing_repo_checkout, "REPO_DIRS", id="repo_dir_missing"),
    ],
)
def test_unexpected_exception_in_a_step_fails_the_run_with_the_error_recorded(
    client, cron_settings, fake_processes, linear_transport, break_a_step, expected_in_message
):
    """One bad step must not cost the whole pass (§2, §4 C5.5).

    A cron pass is several independent steps, and the things that break them are not
    the tidy failures the code was written around: the network is down, or a path in
    the environment points at nothing. Neither is a reason to lose the steps that
    would have worked, and neither may escape as a traceback into a detached worker
    where nobody reads it — so in both cases the run still reaches ``finished`` and
    the reason lands on the alerts page, which is the only place a human looks.

    The two cases are the two shapes that failure takes. An unreachable Linear is a
    surprise from outside our code, and the alert has to carry what actually went
    wrong rather than a generic "step failed", or the operator cannot tell a dead
    network from a bad API key. A ``REPO_DIRS`` entry naming a directory that does
    not exist is unusable configuration (§2): the alert names the variable to fix,
    and the cron never quietly guesses another directory to run a session in.
    """
    break_a_step(cron_settings, linear_transport)
    fake_processes.on("claude", stdout=fakes.claude_result(result="no brief"))

    run = run_cron(client)

    assert run["status"] == "finished", run

    alerts = client.get("/alerts").json()
    matching = [
        alert
        for alert in alerts
        if alert["kind"] == "cron_error" and expected_in_message in alert["message"]
    ]
    assert len(matching) == 1, alerts
