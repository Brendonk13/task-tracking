"""``manage.py run_cron`` — trigger a cron run from a shell or a scheduler."""

from django.core.management.base import BaseCommand

from tracker import models
from tracker.services import crons


class Command(BaseCommand):
    help = "Execute a cron run, either one already recorded or a new one."

    def add_arguments(self, parser):
        parser.add_argument(
            "run_id",
            nargs="?",
            type=int,
            help="Execute the run already recorded under this id.",
        )
        parser.add_argument(
            "--new", action="store_true", help="Start a new run instead of resuming."
        )
        parser.add_argument(
            "--trigger",
            choices=[choice.value for choice in models.CronRunTrigger],
            default=models.CronRunTrigger.COMMAND,
            help="Who asked for this run.",
        )

    def handle(self, *args, **options):
        """Do the run named on the command line, or start one when none is named.

        A detached worker is handed the id of the run ``POST /crons/run`` already
        recorded, precisely so it does *that* run: a worker that started one of its own
        would leave the recorded row ``running`` for ever, and the frontend, which
        follows the id it was given, would watch a run nobody was doing.
        """
        run_id = options["run_id"]
        if run_id is None:
            run = crons.start_run(options["trigger"])
        else:
            run = models.CronRun.objects.get(pk=run_id)
        crons.execute(run)
