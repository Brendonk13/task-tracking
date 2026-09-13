import type { TicketListItem } from "@/api/hooks/tickets"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const priorityClassName: Record<TicketListItem["priority"], string> = {
  urgent: "bg-destructive/15 text-destructive border-destructive/30",
  high: "bg-orange-500/15 text-orange-700 border-orange-500/30 dark:text-orange-300",
  medium: "bg-amber-500/15 text-amber-700 border-amber-500/30 dark:text-amber-300",
  low: "bg-sky-500/15 text-sky-700 border-sky-500/30 dark:text-sky-300",
  none: "bg-muted text-muted-foreground",
}

export function PriorityBadge({ priority }: { priority: TicketListItem["priority"] }) {
  return (
    <Badge variant="outline" className={cn("capitalize", priorityClassName[priority])}>
      {priority}
    </Badge>
  )
}

export function StatusChip({ status }: { status: string | null }) {
  if (status === null) {
    return (
      <Badge variant="outline" className="text-muted-foreground italic">
        no status
      </Badge>
    )
  }
  return <Badge variant="secondary">{status}</Badge>
}
