import { http, HttpResponse } from "msw"
import type { components } from "@/api/schema.d.ts"
import { server } from "./msw"

type TicketsSummary = components["schemas"]["TicketsSummary"]

/** MSW handler for `GET /api/tickets/summary` returning the given badge count. */
export function summaryHandler(needs_human_eyes_count: number) {
  return http.get("/api/tickets/summary", () => {
    const body: TicketsSummary = { needs_human_eyes_count }
    return HttpResponse.json(body)
  })
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
