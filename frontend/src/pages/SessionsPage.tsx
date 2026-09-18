import { Link } from "react-router-dom"
import { useSessions } from "@/api/hooks/sessions"
import type { components } from "@/api/schema.d.ts"
import { ResumeSessionButton } from "@/components/sessions/ResumeSessionButton"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatRelativeTime } from "@/lib/time"

type SessionStatus = components["schemas"]["Session"]["status"]

const EM_DASH = "\u2014"

/**
 * The status of a managed session as a chip; a manual session has no status and reads as an
 * em dash. Only the em-dash branch carries a `session-status` slot: a managed session puts
 * its status in the badge's own text, which is where a reader — and a test — finds the value.
 */
function SessionStatusChip({ status }: { status: SessionStatus }) {
  if (status === null) {
    return (
      <span data-slot="session-status" className="text-muted-foreground">
        {EM_DASH}
      </span>
    )
  }
  return <Badge variant="secondary">{status}</Badge>
}

export function SessionsPage() {
  const { data: sessions, isPending, isError } = useSessions()

  return (
    <section aria-labelledby="sessions-heading" className="flex flex-col gap-4">
      <h1 id="sessions-heading" className="text-2xl font-semibold tracking-tight">
        Sessions
      </h1>

      {isPending && <p className="text-sm text-muted-foreground">Loading sessions…</p>}
      {isError && (
        <p role="alert" className="text-sm text-destructive">
          Could not load sessions.
        </p>
      )}

      {sessions && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-40">Name</TableHead>
              <TableHead>Directory</TableHead>
              <TableHead className="w-24">Ticket</TableHead>
              <TableHead className="w-32">Purpose</TableHead>
              <TableHead className="w-36">Model</TableHead>
              <TableHead className="w-28">Status</TableHead>
              <TableHead>Last message</TableHead>
              <TableHead className="w-36">Last activity</TableHead>
              <TableHead className="w-12">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sessions.map((session) => (
              <TableRow key={session.session_id}>
                <TableCell className="font-medium">{session.name}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {session.directory}
                </TableCell>
                <TableCell>
                  {session.ticket_id !== null && (
                    <Link
                      to={`/tickets/${session.ticket_id}`}
                      className="underline-offset-4 hover:underline"
                    >
                      #{session.ticket_id}
                    </Link>
                  )}
                </TableCell>
                <TableCell data-slot="session-purpose" className="capitalize">
                  {session.purpose.replace("_", " ")}
                </TableCell>
                <TableCell data-slot="session-model" className="text-muted-foreground">
                  {session.model !== null && session.effort !== null
                    ? `${session.model} / ${session.effort}`
                    : EM_DASH}
                </TableCell>
                <TableCell>
                  <SessionStatusChip status={session.status} />
                </TableCell>
                <TableCell>
                  {session.last_message ?? (
                    <span className="text-muted-foreground italic">no messages yet</span>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {session.last_message_at !== null && (
                    <time dateTime={session.last_message_at}>
                      {formatRelativeTime(session.last_message_at)}
                    </time>
                  )}
                </TableCell>
                <TableCell>
                  <ResumeSessionButton
                    sessionId={session.session_id}
                    directory={session.directory}
                    name={session.name}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  )
}
