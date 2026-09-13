import { useRef, useState } from "react"
import { ExternalLink } from "lucide-react"
import { useParams } from "react-router-dom"
import { useStatuses } from "@/api/hooks/statuses"
import {
  useAddComment,
  useChangeStatus,
  useSetNeedsHumanEyes,
  useTicket,
  type TicketDetail,
  type TimelineEntry,
} from "@/api/hooks/tickets"
import { ResumeSessionButton } from "@/components/sessions/ResumeSessionButton"
import { PriorityBadge, StatusChip } from "@/components/tickets/TicketBadges"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"

const OTHER_STATUS = "__other__"

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

  return (
    <li data-kind={entry.kind} className="flex flex-col gap-1">
      {meta}
      {entry.kind === "comment" ? (
        <article className="rounded-lg border bg-card px-3 py-2 text-sm text-card-foreground shadow-xs whitespace-pre-wrap">
          {entry.body}
        </article>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">{entry.body}</p>
          {entry.reason !== null && (
            <p className="text-sm">
              <span className="text-muted-foreground">Reason: </span>
              <span className="italic">{entry.reason}</span>
            </p>
          )}
        </>
      )}
    </li>
  )
}

function CommentForm({ ticketId }: { ticketId: number }) {
  const [body, setBody] = useState("")
  const bodyRef = useRef<HTMLTextAreaElement>(null)
  const addComment = useAddComment(ticketId)

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        const trimmed = body.trim()
        if (trimmed === "") return
        addComment.mutate(trimmed, {
          onSuccess: () => {
            setBody("")
            bodyRef.current?.focus()
          },
        })
      }}
    >
      <Label htmlFor="comment-body">Comment</Label>
      <Textarea
        ref={bodyRef}
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

function StatusForm({ ticket }: { ticket: TicketDetail }) {
  const { data: statuses } = useStatuses()
  const [selected, setSelected] = useState(ticket.status ?? "")
  const [newStatus, setNewStatus] = useState("")
  const [reason, setReason] = useState("")
  const reasonRef = useRef<HTMLInputElement>(null)
  const changeStatus = useChangeStatus(ticket.id)

  const status = selected === OTHER_STATUS ? newStatus.trim() : selected
  const canSubmit = status !== "" && reason.trim() !== "" && !changeStatus.isPending

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        if (!canSubmit) return
        changeStatus.mutate(
          { status, reason: reason.trim() },
          {
            onSuccess: (detail) => {
              setSelected(detail.status ?? "")
              setNewStatus("")
              setReason("")
              reasonRef.current?.focus()
            },
          },
        )
      }}
    >
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor="status-select">Status</Label>
          <select
            id="status-select"
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            className="h-8 min-w-40 rounded-md border border-input bg-background px-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {ticket.status === null && (
              <option value="" disabled>
                no status
              </option>
            )}
            {statuses?.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
            <option value={OTHER_STATUS}>Other…</option>
          </select>
        </div>
        {selected === OTHER_STATUS && (
          <div className="flex flex-col gap-1">
            <Label htmlFor="new-status">New status</Label>
            <Input
              id="new-status"
              value={newStatus}
              onChange={(event) => setNewStatus(event.target.value)}
              placeholder="waiting-on-vendor"
              className="h-8"
            />
          </div>
        )}
        <div className="flex min-w-56 flex-1 flex-col gap-1">
          <Label htmlFor="status-reason">Reason</Label>
          <Input
            ref={reasonRef}
            id="status-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Why is the status changing?"
            className="h-8"
          />
        </div>
        <Button type="submit" size="sm" disabled={!canSubmit}>
          Change status
        </Button>
      </div>
      {changeStatus.isError && (
        <p role="alert" className="text-sm text-destructive">
          Could not change status.
        </p>
      )}
    </form>
  )
}

function NeedsHumanEyesToggle({ ticket }: { ticket: TicketDetail }) {
  const setFlag = useSetNeedsHumanEyes(ticket.id)
  return (
    <div className="flex items-center gap-2">
      <Switch
        id="needs-human-eyes"
        checked={ticket.needs_human_eyes}
        disabled={setFlag.isPending}
        onCheckedChange={(checked) => setFlag.mutate(checked)}
      />
      <Label htmlFor="needs-human-eyes">Needs human eyes</Label>
    </div>
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
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">{ticket.title}</h1>
          <div className="flex flex-wrap items-center gap-4">
            {ticket.linear_url !== null && (
              <a
                href={ticket.linear_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline"
              >
                Open in Linear
                <ExternalLink aria-hidden="true" className="size-3.5" />
              </a>
            )}
            <NeedsHumanEyesToggle ticket={ticket} />
          </div>
        </div>
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

      <section aria-label="Change status" className="border-t pt-3">
        <StatusForm ticket={ticket} />
      </section>

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
