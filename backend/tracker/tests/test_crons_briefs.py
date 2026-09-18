import pytest

from tracker.tests import fakes
from tracker.tests.conftest import run_cron

pytestmark = pytest.mark.django_db

BRIEF_REPO = "mosaic-avantos/avantos"


def test_new_ticket_gets_a_managed_session_linked_to_it_before_claude_is_invoked(
    client, cron_settings, fake_processes, linear_transport
):
    """The session row exists before the process it describes does (§4 C2.1).

    A human watching the sessions page must never see a ``claude`` running with no
    row to explain it — so the row is written first, already linked to its ticket
    and already marked ``running``, and only then is the process started. The fake
    ``claude`` therefore asks the API what it can see at the exact moment it is
    invoked; the assertions are made against that snapshot, not against the state
    after the run, which would say nothing about ordering.
    """
    linear_transport.serve("linear/assigned_page1.json", "linear/assigned_page2.json")

    sessions_when_claude_started: list[list[dict]] = []
    fake_processes.on(
        "claude",
        stdout=fakes.claude_result(
            {
                "md_path": f"{cron_settings.BRIEFS_DIR}/2026-09-17-CON-7.md",
                "html_path": f"{cron_settings.BRIEFS_DIR}/2026-09-17-CON-7.html",
                "next_step": "diagnose",
                "summary": "CON-7 is a bug in the external handoff dispatcher.",
            }
        ),
        side_effect=lambda call: sessions_when_claude_started.append(
            client.get("/sessions").json()
        ),
    )

    run_cron(client)

    assert fake_processes.calls_to("claude"), "no claude process was started at all"

    con7 = next(
        ticket
        for ticket in client.get("/tickets").json()
        if ticket["linear_identifier"] == "CON-7"
    )
    already_listed = {
        session["session_id"]: session
        for snapshot in sessions_when_claude_started
        for session in snapshot
    }
    for_con7 = [s for s in already_listed.values() if s["ticket_id"] == con7["id"]]
    assert len(for_con7) == 1, already_listed

    session = for_con7[0]
    assert session["purpose"] == "ticket_brief"
    assert session["status"] == "running"
    assert session["model"] == "opus"
    assert session["effort"] == "high"
    assert session["directory"] == cron_settings.REPO_DIRS[BRIEF_REPO]
