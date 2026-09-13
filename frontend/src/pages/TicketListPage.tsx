import { useState } from "react"
import { TriangleAlert } from "lucide-react"
import { useTickets, type TicketListItem, type TicketListQuery } from "@/api/hooks/tickets"
import { StatusFilter } from "@/components/tickets/StatusFilter"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

const priorityClassName: Record<TicketListItem["priority"], string> = {
  urgent: "bg-destructive/15 text-destructive border-destructive/30",
  high: "bg-orange-500/15 text-orange-700 border-orange-500/30 dark:text-orange-300",
  medium: "bg-amber-500/15 text-amber-700 border-amber-500/30 dark:text-amber-300",
  low: "bg-sky-500/15 text-sky-700 border-sky-500/30 dark:text-sky-300",
  none: "bg-muted text-muted-foreground",
}

function PriorityBadge({ priority }: { priority: TicketListItem["priority"] }) {
  return (
    <Badge variant="outline" className={cn("capitalize", priorityClassName[priority])}>
      {priority}
    </Badge>
  )
}

function StatusChip({ status }: { status: string | null }) {
  if (status === null) {
    return (
      <Badge variant="outline" className="text-muted-foreground italic">
        no status
      </Badge>
    )
  }
  return <Badge variant="secondary">{status}</Badge>
}

type SortField = NonNullable<TicketListQuery["sort"]>

const sortOptions: { value: SortField; label: string }[] = [
  { value: "created_at", label: "Newest" },
  { value: "updated_at", label: "Recently updated" },
  { value: "priority", label: "Priority" },
]

export function TicketListPage() {
  const [statuses, setStatuses] = useState<string[]>([])
  const [needsHumanEyes, setNeedsHumanEyes] = useState(false)
  const [sort, setSort] = useState<SortField>("created_at")

  const query: TicketListQuery = { sort, order: "desc" }
  if (statuses.length > 0) query.status = statuses
  if (needsHumanEyes) query.needs_human_eyes = true

  const { data: tickets, isPending, isError } = useTickets(query)

  return (
    <section aria-labelledby="tickets-heading" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 id="tickets-heading" className="text-2xl font-semibold tracking-tight">
          Tickets
        </h1>
        <div role="toolbar" aria-label="Ticket filters" className="flex flex-wrap items-center gap-4">
          <StatusFilter selected={statuses} onChange={setStatuses} />
          <div className="flex items-center gap-2">
            <Switch
              id="needs-human-eyes-filter"
              checked={needsHumanEyes}
              onCheckedChange={setNeedsHumanEyes}
            />
            <Label htmlFor="needs-human-eyes-filter">Needs human eyes</Label>
          </div>
          <select
            aria-label="Sort by"
            value={sort}
            onChange={(event) => setSort(event.target.value as SortField)}
            className="h-8 rounded-md border border-input bg-background px-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {sortOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {isPending && <p className="text-sm text-muted-foreground">Loading tickets…</p>}
      {isError && (
        <p role="alert" className="text-sm text-destructive">
          Could not load tickets.
        </p>
      )}

      {tickets && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8">
                <span className="sr-only">Flags</span>
              </TableHead>
              <TableHead>Title</TableHead>
              <TableHead className="w-28">Priority</TableHead>
              <TableHead className="w-44">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tickets.map((ticket) => (
              <TableRow
                key={ticket.id}
                data-needs-human-eyes={String(ticket.needs_human_eyes)}
                className={cn(
                  ticket.needs_human_eyes &&
                    "border-l-2 border-l-destructive bg-destructive/5 hover:bg-destructive/10",
                )}
              >
                <TableCell>
                  {ticket.needs_human_eyes && (
                    <TriangleAlert
                      aria-label="Needs human eyes"
                      role="img"
                      className="size-4 text-destructive"
                    />
                  )}
                </TableCell>
                <TableCell className="font-medium">{ticket.title}</TableCell>
                <TableCell>
                  <PriorityBadge priority={ticket.priority} />
                </TableCell>
                <TableCell>
                  <StatusChip status={ticket.status} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  )
}
