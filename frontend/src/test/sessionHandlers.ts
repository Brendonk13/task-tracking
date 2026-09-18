import { http, HttpResponse } from "msw"
import type { components } from "@/api/schema.d.ts"

type Session = components["schemas"]["Session"]

let nextSessionNumber = 1

/**
 * Builds a `Session` (memo A10: `last_message`/`last_message_at` nullable) with sensible
 * defaults; `session_id`s auto-increment per test file. Defaults to a session with no
 * messages yet.
 */
export function makeSession(overrides: Partial<Session> = {}): Session {
  const n = nextSessionNumber++
  return {
    session_id: `sess-${n}`,
    name: `session-${n}`,
    directory: `/home/dev/project-${n}`,
    last_message: null,
    last_message_at: null,
    ticket_id: null,
    // Defaults describe a session a human registered by hand: nothing managed it.
    purpose: "manual",
    model: null,
    effort: null,
    status: null,
    result_summary: null,
    finished_at: null,
    created_at: "2026-09-12T10:00:00Z",
    ...overrides,
  }
}

/**
 * MSW handler for `GET /api/sessions` returning the given rows verbatim, in the given order.
 * The server already sorts (A10), so the page must not re-sort.
 */
export function sessionsHandler(rows: Session[]) {
  return http.get("/api/sessions", () => HttpResponse.json(rows))
}
