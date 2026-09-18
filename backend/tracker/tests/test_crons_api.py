import sys

import pytest

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
