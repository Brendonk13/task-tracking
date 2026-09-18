"""``manage.py run_cron`` — trigger a cron run from a shell or a scheduler."""

from django.core.management.base import BaseCommand

from tracker import models
from tracker.services import crons


class Command(BaseCommand):
    help = "Start a cron run and execute it in this process."

    def add_arguments(self, parser):
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
        run = crons.start_run(options["trigger"])
        crons.execute(run)
