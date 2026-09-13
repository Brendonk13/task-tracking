import { useTickets, type TicketListItem } from "@/api/hooks/tickets"
import { Badge } from "@/components/ui/badge"
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

export function TicketListPage() {
  const { data: tickets, isPending, isError } = useTickets()

  return (
    <section aria-labelledby="tickets-heading" className="flex flex-col gap-4">
      <h1 id="tickets-heading" className="text-2xl font-semibold tracking-tight">
        Tickets
      </h1>

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
              <TableHead>Title</TableHead>
              <TableHead className="w-28">Priority</TableHead>
              <TableHead className="w-44">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tickets.map((ticket) => (
              <TableRow key={ticket.id}>
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
