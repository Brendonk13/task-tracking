"""Sessions: naming them, and creating the ones this app starts itself.

A session registered through the API describes a process that already exists. A
managed session is the opposite: the row has to exist before the process does, so a
human watching the sessions page never sees a ``claude`` running with nothing to
explain it, and so the crash of a run still leaves the session behind to be found.
"""

import uuid

from tracker import models
from tracker.services import names

MAX_NAME_ATTEMPTS = 100


def unused_name() -> str:
    """A generated name no session holds yet.

    Names are unique so people can say them out loud; the generator draws at random, so
    collisions are ordinary and are simply redrawn rather than being an error.
    """
    for _ in range(MAX_NAME_ATTEMPTS):
        name = names.generate_name()
        if not models.Session.objects.filter(name=name).exists():
            return name
    raise RuntimeError("could not generate a unique session name")


def create_managed_session(
    *,
    purpose: models.SessionPurpose | str,
    directory: str,
    model: str,
    effort: str,
    ticket: models.Ticket | None = None,
    cron_run: models.CronRun | None = None,
) -> models.Session:
    """Write the row for a session we are about to start, already marked ``running``.

    The id is drawn here rather than read back out of the process, for two reasons: it
    has to be passed to ``claude --session-id`` so the transcript is resumable later
    with ``claude --resume <id>``, and the row cannot be written first if the id only
    arrives afterwards.
    """
    return models.Session.objects.create(
        session_id=str(uuid.uuid4()),
        name=unused_name(),
        directory=directory,
        purpose=purpose,
        model=model,
        effort=effort,
        status=models.SessionStatus.RUNNING,
        ticket=ticket,
        cron_run=cron_run,
    )
