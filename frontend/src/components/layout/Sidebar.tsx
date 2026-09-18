import { useState } from "react"
import { Bell, PanelLeftClose, PanelLeftOpen, SquareTerminal, Ticket } from "lucide-react"
import { NavLink } from "react-router-dom"
import { useAlertsSummary } from "@/api/hooks/alerts"
import { useTicketsSummary } from "@/api/hooks/tickets"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/** Which count a nav item's badge shows, if any. */
type BadgeKind = "needs_human_eyes" | "alerts"

interface NavItem {
  to: string
  label: string
  icon: typeof Ticket
  badge?: BadgeKind
}

const navItems: NavItem[] = [
  { to: "/", label: "Tickets", icon: Ticket, badge: "needs_human_eyes" },
  { to: "/sessions", label: "Sessions", icon: SquareTerminal },
  { to: "/alerts", label: "Alerts", icon: Bell, badge: "alerts" },
]

function badgeLabel(kind: BadgeKind, count: number): string {
  if (kind === "alerts") return `${count} ${count === 1 ? "alert" : "alerts"}`
  return `${count} ${count === 1 ? "ticket needs" : "tickets need"} human eyes`
}

function CountBadge({
  kind,
  count,
  collapsed,
}: {
  kind: BadgeKind
  count: number
  collapsed: boolean
}) {
  if (count <= 0) return null
  return (
    <span
      role="status"
      aria-label={badgeLabel(kind, count)}
      className={cn(
        "inline-flex items-center justify-center rounded-full bg-destructive font-semibold text-white tabular-nums",
        collapsed
          ? "absolute -top-1 -right-1 h-4 min-w-4 px-1 text-[10px] leading-none"
          : "ml-auto h-5 min-w-5 px-1.5 text-xs",
      )}
    >
      {count}
    </span>
  )
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const { data: summary } = useTicketsSummary()
  const { data: alertsSummary } = useAlertsSummary()
  const counts: Record<BadgeKind, number> = {
    needs_human_eyes: summary?.needs_human_eyes_count ?? 0,
    alerts: alertsSummary?.undismissed_count ?? 0,
  }
  const ToggleIcon = collapsed ? PanelLeftOpen : PanelLeftClose

  return (
    <aside
      className={cn(
        "flex shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width]",
        collapsed ? "w-14" : "w-56",
      )}
    >
      <div
        className={cn(
          "flex h-14 items-center gap-2 px-2",
          collapsed ? "justify-center" : "justify-between",
        )}
      >
        {!collapsed && (
          <span className="truncate px-2 text-sm font-semibold tracking-tight">Task Tracking</span>
        )}
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={() => setCollapsed((c) => !c)}
        >
          <ToggleIcon aria-hidden="true" />
        </Button>
      </div>
      <nav aria-label="Main" className="flex flex-col gap-1 px-2">
        {navItems.map(({ to, label, icon: Icon, badge }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            aria-label={collapsed ? label : undefined}
            title={collapsed ? label : undefined}
            className={({ isActive }) =>
              cn(
                "relative flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium transition-colors outline-none",
                "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                "focus-visible:ring-2 focus-visible:ring-sidebar-ring",
                collapsed && "justify-center",
                isActive && "bg-sidebar-accent text-sidebar-accent-foreground",
              )
            }
          >
            <span className="relative inline-flex shrink-0">
              <Icon aria-hidden="true" className="size-4" />
              {badge && collapsed && <CountBadge kind={badge} count={counts[badge]} collapsed />}
            </span>
            {!collapsed && <span>{label}</span>}
            {badge && !collapsed && (
              <CountBadge kind={badge} count={counts[badge]} collapsed={false} />
            )}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
