"""The one place this app starts, or looks at, an external process.

Everything that shells out — the ``gh`` client, the headless ``claude`` runner, the
detached cron worker — goes through these three module-level attributes and nothing
else. That makes them the single seam a test swaps (see PLAN crons §3, S3): tests
replace ``run``/``popen``/``pid_alive`` with a fake, so our argv building, parsing and
allow/deny lists still run for real while no real process is started.

Production code must call them as attributes (``processes.run(...)``), never import
the names, or monkeypatching would not be seen.
"""

import os
import subprocess

# ``subprocess.run(argv, ...)`` — used for anything we wait for.
run = subprocess.run

# ``subprocess.Popen(argv, ...)`` — used for the detached cron worker.
popen = subprocess.Popen


def _pid_alive(pid: int) -> bool:
    """Is a process with this pid still around? Signal 0 checks without sending."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists, it just is not ours.
        return True
    return True


pid_alive = _pid_alive
