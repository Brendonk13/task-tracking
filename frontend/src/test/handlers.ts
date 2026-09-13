import { http, HttpResponse } from "msw"
import type { components } from "@/api/schema.d.ts"
import { server } from "./msw"

type TicketsSummary = components["schemas"]["TicketsSummary"]
type TicketListItem = components["schemas"]["TicketListItem"]
type StatusItem = components["schemas"]["StatusItem"]

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
 * Resolver for `ticketsHandler` that mimics the backend's status filter: repeated `status=`
 * params are OR-ed; no `status` param returns everything.
 */
export function filterByStatus(rows: TicketListItem[]) {
  return (url: URL) => {
    const wanted = url.searchParams.getAll("status")
    return wanted.length === 0 ? rows : rows.filter((t) => t.status !== null && wanted.includes(t.status))
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
