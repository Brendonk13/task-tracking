import { useState } from "react"
import { useParams } from "react-router-dom"
import { useAddComment, useTicket, type TimelineEntry } from "@/api/hooks/tickets"
import { ResumeSessionButton } from "@/components/sessions/ResumeSessionButton"
import { PriorityBadge, StatusChip } from "@/components/tickets/TicketBadges"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

function TimelineItem({ entry }: { entry: TimelineEntry }) {
  const meta = (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span data-slot="timeline-actor" className="font-medium text-foreground">
        {entry.actor.name}
      </span>
      <time dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleString()}</time>
      {entry.actor.directory !== null && (
        <ResumeSessionButton
          sessionId={entry.actor.session_id}
          directory={entry.actor.directory}
          name={entry.actor.name}
        />
      )}
    </div>
  )

  if (entry.kind === "comment") {
    return (
      <li data-kind={entry.kind} className="flex flex-col gap-1">
        {meta}
        <article className="rounded-lg border bg-card px-3 py-2 text-sm text-card-foreground shadow-xs whitespace-pre-wrap">
          {entry.body}
        </article>
      </li>
    )
  }
  return (
    <li data-kind={entry.kind} className="flex flex-col gap-1">
      {meta}
      <p className="text-sm text-muted-foreground">{entry.body}</p>
      {entry.reason !== null && (
        <p className="text-sm">
          <span className="text-muted-foreground">Reason: </span>
          <span className="italic">{entry.reason}</span>
        </p>
      )}
    </li>
  )
}

function CommentForm({ ticketId }: { ticketId: number }) {
  const [body, setBody] = useState("")
  const addComment = useAddComment(ticketId)

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        const trimmed = body.trim()
        if (trimmed === "") return
        addComment.mutate(trimmed, { onSuccess: () => setBody("") })
      }}
    >
      <Label htmlFor="comment-body">Comment</Label>
      <Textarea
        id="comment-body"
        value={body}
        onChange={(event) => setBody(event.target.value)}
        placeholder="Leave a note for the sessions working on this ticket"
        rows={3}
      />
      {addComment.isError && (
        <p role="alert" className="text-sm text-destructive">
          Could not post comment.
        </p>
      )}
      <div>
        <Button type="submit" size="sm" disabled={addComment.isPending || body.trim() === ""}>
          Post comment
        </Button>
      </div>
    </form>
  )
}

export function TicketDetailPage() {
  const { id } = useParams()
  const ticketId = Number(id)
  const { data: ticket, isPending, isError } = useTicket(ticketId)

  if (isPending) return <p className="text-sm text-muted-foreground">Loading ticket…</p>
  if (isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Could not load ticket.
      </p>
    )
  }

  return (
    <article className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{ticket.title}</h1>
        <div className="flex flex-wrap items-center gap-2">
          <PriorityBadge priority={ticket.priority} />
          <StatusChip status={ticket.status} />
          {ticket.project !== null && <Badge variant="outline">{ticket.project}</Badge>}
          {ticket.labels.map((label) => (
            <Badge key={label} variant="secondary">
              {label}
            </Badge>
          ))}
        </div>
        {ticket.description !== "" && (
          <p className="text-sm text-foreground/90 whitespace-pre-wrap">{ticket.description}</p>
        )}
      </header>

      <section aria-labelledby="timeline-heading" className="flex flex-col gap-3">
        <h2 id="timeline-heading" className="text-lg font-medium">
          Timeline
        </h2>
        <ol aria-label="Timeline" className="flex flex-col gap-3 border-l pl-4">
          {ticket.timeline.map((entry) => (
            <TimelineItem key={entry.id} entry={entry} />
          ))}
        </ol>
        <CommentForm ticketId={ticketId} />
      </section>
    </article>
  )
}
