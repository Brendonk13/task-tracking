import { http, HttpResponse } from "msw"
import type { components } from "@/api/schema.d.ts"
import { server } from "./msw"

type TicketsSummary = components["schemas"]["TicketsSummary"]
type TicketListItem = components["schemas"]["TicketListItem"]
type StatusItem = components["schemas"]["StatusItem"]
type TicketDetail = components["schemas"]["TicketDetail"]
type TimelineEntry = components["schemas"]["TimelineEntry"]

/** The ten built-in statuses, in the canonical order `GET /api/statuses` returns them. */
export const BUILT_IN_STATUSES: StatusItem[] = [
  "blocked",
  "needs-help",
  "planning",
  "implementing-plan",
  "diagnosing-ticket",
  "needs-clarification",
  "ready-for-pr",
  "merged",
  "tested-in-cloud",
  "done",
].map((name) => ({ name, is_builtin: true }))

let nextTicketId = 1

/** Builds a `TicketListItem` with sensible defaults; ids auto-increment per test file. */
export function makeTicket(overrides: Partial<TicketListItem> = {}): TicketListItem {
  const id = overrides.id ?? nextTicketId++
  return {
    id,
    title: `Ticket ${id}`,
    priority: "none",
    status: null,
    needs_human_eyes: false,
    project: null,
    labels: [],
    linear_url: null,
    created_at: "2026-09-12T10:00:00Z",
    updated_at: "2026-09-12T10:00:00Z",
    ...overrides,
  }
}

let nextEntryId = 1

/**
 * Builds a `TimelineEntry` (A2: one flat schema, inapplicable fields `null`).
 * Defaults to a comment by the session `cool-willow`; ids auto-increment per test file.
 */
export function makeTimelineEntry(overrides: Partial<TimelineEntry> = {}): TimelineEntry {
  const id = overrides.id ?? nextEntryId++
  return {
    id,
    kind: "comment",
    actor: { session_id: "sess-1", name: "cool-willow", directory: "/home/dev/app" },
    body: `Comment ${id}`,
    created_at: "2026-09-12T10:00:00Z",
    from_status: null,
    to_status: null,
    reason: null,
    ...overrides,
  }
}

/** Builds a `TicketDetail` on top of `makeTicket` defaults, with an empty description and timeline. */
export function makeTicketDetail(overrides: Partial<TicketDetail> = {}): TicketDetail {
  const { description = "", timeline = [], ...listOverrides } = overrides
  return { ...makeTicket(listOverrides), description, timeline }
}

/** MSW handler for `GET /api/tickets/:id` returning the given detail for its own id. */
export function ticketDetailHandler(detail: TicketDetail) {
  return http.get(`/api/tickets/${detail.id}`, () => HttpResponse.json(detail))
}

/** MSW handler for `GET /api/tickets/summary` returning the given badge count. */
export function summaryHandler(needs_human_eyes_count: number) {
  return http.get("/api/tickets/summary", () => {
    const body: TicketsSummary = { needs_human_eyes_count }
    return HttpResponse.json(body)
  })
}

/**
 * MSW handler for `GET /api/tickets` (any query string). Pass either a fixed array of rows,
 * or a resolver that receives the request URL and returns the rows for that query.
 */
export function ticketsHandler(rows: TicketListItem[] | ((url: URL) => TicketListItem[])) {
  return http.get("/api/tickets", ({ request }) => {
    const url = new URL(request.url)
    return HttpResponse.json(typeof rows === "function" ? rows(url) : rows)
  })
}

/**
 * Resolver for `ticketsHandler` that mimics the backend's list filters:
 * repeated `status=` params are OR-ed (none → no status filter), and
 * `needs_human_eyes=true|false` keeps only matching rows. Sorting is not mimicked.
 */
export function filterTickets(rows: TicketListItem[]) {
  return (url: URL) => {
    const statuses = url.searchParams.getAll("status")
    const flag = url.searchParams.get("needs_human_eyes")
    return rows.filter((t) => {
      if (statuses.length > 0 && (t.status === null || !statuses.includes(t.status))) return false
      if (flag !== null && t.needs_human_eyes !== (flag === "true")) return false
      return true
    })
  }
}

/** MSW handler for `GET /api/statuses`; defaults to the ten built-ins. */
export function statusesHandler(items: StatusItem[] = BUILT_IN_STATUSES) {
  return http.get("/api/statuses", () => HttpResponse.json(items))
}

/**
 * Records the pathname of every request MSW sees for the rest of the current test.
 * Listeners are removed in ./setup.ts after each test.
 */
export function recordRequests(): string[] {
  const paths: string[] = []
  server.events.on("request:start", ({ request }) => {
    paths.push(new URL(request.url).pathname)
  })
  return paths
}

/**
 * Records the query string of every request to `pathname` for the rest of the current test,
 * in order. Listeners are removed in ./setup.ts after each test.
 */
export function recordSearchParams(pathname = "/api/tickets"): URLSearchParams[] {
  const seen: URLSearchParams[] = []
  server.events.on("request:start", ({ request }) => {
    const url = new URL(request.url)
    if (url.pathname === pathname) seen.push(url.searchParams)
  })
  return seen
}
