import { Play } from "lucide-react";
import {
  useCronsSummary,
  useRunCrons,
  type CronsSummary,
} from "@/api/hooks/crons";
import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/time";

/** One sentence about the crons: what is happening now, or how the last pass ended. */
function describe(summary: CronsSummary | undefined): string {
  if (summary === undefined) return "";
  const lastRun = summary.last_run;
  if (lastRun === null) return "No runs yet";
  if (summary.running)
    return `Running since ${formatRelativeTime(lastRun.started_at)}`;
  const ended = lastRun.finished_at ?? lastRun.started_at;
  return `Last run: ${lastRun.status} ${formatRelativeTime(ended)}`;
}

/**
 * Starts a cron pass and says what the crons are doing. The button is disabled while a pass is
 * in flight, because the backend refuses a second one (C5.2).
 */
export function RunCronsButton() {
  const summary = useCronsSummary();
  const run = useRunCrons();
  const isRunning = summary.data?.running === true;

  return (
    <div className="flex items-center gap-3">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={isRunning || run.isPending}
        onClick={() => run.mutate()}
      >
        <Play aria-hidden="true" />
        Run crons
      </Button>
      <span role="status" className="text-sm text-muted-foreground">
        {describe(summary.data)}
      </span>
    </div>
  );
}
