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

/** MSW handler for `GET /api/tickets/summary` returning the given badge count. */
export function summaryHandler(needs_human_eyes_count: number) {
  return http.get("/api/tickets/summary", () => {
    const body: TicketsSummary = { needs_human_eyes_count }
    return HttpResponse.json(body)
  })
}

/** MSW handler for `GET /api/tickets` (any query string) returning the given rows. */
export function ticketsHandler(rows: TicketListItem[]) {
  return http.get("/api/tickets", () => HttpResponse.json(rows))
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
