import { Link } from "react-router-dom"
import { ExternalLink } from "lucide-react"
import { useAlerts } from "@/api/hooks/alerts"
import { usePullRequests } from "@/api/hooks/pull-requests"
import { ResumeSessionButton } from "@/components/sessions/ResumeSessionButton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatRelativeTime } from "@/lib/time"

export function AlertsPage() {
  const alerts = useAlerts()
  // An alert only names its pull request (id and number), so the GitHub url comes from
  // the pull request listing, matched on id.
  const pullRequests = usePullRequests()
  const isPending = alerts.isPending || pullRequests.isPending
  const isError = alerts.isError || pullRequests.isError
  const urlByPullRequestId = new Map(pullRequests.data?.map((pr) => [pr.id, pr.url]))

  return (
    <section aria-labelledby="alerts-heading" className="flex flex-col gap-4">
      <h1 id="alerts-heading" className="text-2xl font-semibold tracking-tight">
        Alerts
      </h1>

      {isPending && <p className="text-sm text-muted-foreground">Loading alerts…</p>}
      {isError && (
        <p role="alert" className="text-sm text-destructive">
          Could not load alerts.
        </p>
      )}

      {/* The server sorts newest first and hides dismissed alerts, so rows go out as they came in. */}
      {alerts.data && !isPending && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-36">Kind</TableHead>
              <TableHead>Alert</TableHead>
              <TableHead className="w-56">Ticket</TableHead>
              <TableHead className="w-28">Pull request</TableHead>
              <TableHead className="w-36">Raised</TableHead>
              <TableHead className="w-12">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {alerts.data.map((alert) => {
              const pullRequestUrl =
                alert.pull_request === null
                  ? undefined
                  : urlByPullRequestId.get(alert.pull_request.id)
              return (
                <TableRow key={alert.id}>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {alert.kind}
                  </TableCell>
                  <TableCell>{alert.message}</TableCell>
                  <TableCell>
                    {alert.ticket !== null && (
                      <Link
                        to={`/tickets/${alert.ticket.id}`}
                        className="underline-offset-4 hover:underline"
                      >
                        {alert.ticket.title}
                      </Link>
                    )}
                  </TableCell>
                  <TableCell>
                    {alert.pull_request !== null && pullRequestUrl !== undefined && (
                      // The column header already says "pull request", so the cell shows just
                      // the number; the accessible name keeps it readable out of context.
                      <a
                        href={pullRequestUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`PR #${alert.pull_request.number}`}
                        className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"
                      >
                        #{alert.pull_request.number}
                        <ExternalLink aria-hidden="true" className="size-3" />
                      </a>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    <time dateTime={alert.created_at}>{formatRelativeTime(alert.created_at)}</time>
                  </TableCell>
                  <TableCell>
                    {/* A managed run with no directory has nowhere to cd to (F3.5). */}
                    {alert.session !== null && alert.session.directory !== null && (
                      <ResumeSessionButton
                        sessionId={alert.session.session_id}
                        directory={alert.session.directory}
                        name={alert.session.name}
                      />
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </section>
  )
}
