import { ExternalLink } from "lucide-react"
import { usePullRequests, type PullRequest } from "@/api/hooks/pull-requests"
import type { TicketDetail } from "@/api/hooks/tickets"
import { Badge } from "@/components/ui/badge"

type TicketPullRequest = TicketDetail["pull_requests"][number]

function PullRequestRow({
  pullRequest,
  listed,
}: {
  pullRequest: TicketPullRequest
  listed: PullRequest | undefined
}) {
  const commentCount = listed?.comment_count ?? 0
  const session = listed?.last_triage_session ?? null

  return (
    <li className="flex flex-wrap items-center gap-2 py-2 text-sm">
      <a
        href={pullRequest.url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline"
      >
        #{pullRequest.number}
        <ExternalLink aria-hidden="true" className="size-3.5" />
      </a>
      <Badge variant="outline">{pullRequest.state}</Badge>
      <span className="text-muted-foreground">{commentCount} comments</span>
      {session !== null && (
        <span data-slot="pr-triage-session" className="font-medium text-foreground">
          {session.name}
        </span>
      )}
    </li>
  )
}

export function PullRequestList({ ticket }: { ticket: TicketDetail }) {
  // The ticket only names its PRs, so the comment count and the last triage session come from
  // the pull request listing, matched on id. A ticket with no PRs never needs that request.
  const hasPullRequests = ticket.pull_requests.length > 0
  const { data, isPending, isError } = usePullRequests({ enabled: hasPullRequests })
  const byId = new Map((data ?? []).map((pr) => [pr.id, pr]))

  return (
    <section aria-labelledby="pull-requests-heading" className="flex flex-col gap-2">
      <h2 id="pull-requests-heading" className="text-lg font-medium">
        Pull requests
      </h2>
      {!hasPullRequests ? (
        <p className="text-sm text-muted-foreground">No pull requests.</p>
      ) : isPending ? (
        <p className="text-sm text-muted-foreground">Loading pull requests…</p>
      ) : isError ? (
        <p role="alert" className="text-sm text-destructive">
          Could not load pull requests.
        </p>
      ) : (
        <ul aria-label="Pull requests" className="flex flex-col divide-y">
          {ticket.pull_requests.map((pullRequest) => (
            <PullRequestRow
              key={pullRequest.id}
              pullRequest={pullRequest}
              listed={byId.get(pullRequest.id)}
            />
          ))}
        </ul>
      )}
    </section>
  )
}
