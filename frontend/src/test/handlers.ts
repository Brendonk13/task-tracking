import { http, HttpResponse } from "msw"
import type { components } from "@/api/schema.d.ts"
import { server } from "./msw"

type TicketsSummary = components["schemas"]["TicketsSummary"]
type AlertsSummary = components["schemas"]["AlertsSummary"]
type TicketListItem = components["schemas"]["TicketListItem"]
type StatusItem = components["schemas"]["StatusItem"]
type TicketDetail = components["schemas"]["TicketDetail"]
type TimelineEntry = components["schemas"]["TimelineEntry"]
type Actor = components["schemas"]["Actor"]
type CommentIn = components["schemas"]["CommentIn"]
type StatusChangeIn = components["schemas"]["StatusChangeIn"]
type NeedsHumanEyesIn = components["schemas"]["NeedsHumanEyesIn"]
type Task = components["schemas"]["Task"]
type TaskDetail = components["schemas"]["TaskDetail"]
type TaskHistoryEntry = components["schemas"]["TaskHistoryEntry"]
type TaskCreate = components["schemas"]["TaskCreate"]
type TaskStateIn = components["schemas"]["TaskStateIn"]

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
    linear_identifier: null,
    parent_id: null,
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

let nextTaskId = 1

/** Builds a `Task` in state `todo` with no dependencies; ids auto-increment per test file. */
export function makeTask(overrides: Partial<Task> = {}): Task {
  const id = overrides.id ?? nextTaskId++
  return {
    id,
    ticket_id: 1,
    title: `Task ${id}`,
    description: "",
    state: "todo",
    depends_on: [],
    blocked_by: [],
    created_at: "2026-09-12T10:00:00Z",
    updated_at: "2026-09-12T10:00:00Z",
    ...overrides,
  }
}

let nextTaskHistoryId = 1

/** Builds a `TaskHistoryEntry`; defaults to a state change by the session `cool-willow`. */
export function makeTaskHistoryEntry(overrides: Partial<TaskHistoryEntry> = {}): TaskHistoryEntry {
  const id = overrides.id ?? nextTaskHistoryId++
  return {
    id,
    kind: "state_change",
    actor: { session_id: "sess-1", name: "cool-willow", directory: "/home/dev/app" },
    body: "cool-willow changed state from todo to in_progress",
    created_at: "2026-09-12T10:00:00Z",
    from_state: "todo",
    to_state: "in_progress",
    reason: null,
    ...overrides,
  }
}

/** Builds a `TaskDetail` on top of `makeTask` defaults, with an empty history. */
export function makeTaskDetail(overrides: Partial<TaskDetail> = {}): TaskDetail {
  const { history = [], ...taskOverrides } = overrides
  return { ...makeTask(taskOverrides), history }
}

/**
 * Builds a `TicketDetail` on top of `makeTicket` defaults, with an empty description,
 * timeline and task list, and no parent or sub-tickets.
 */
export function makeTicketDetail(overrides: Partial<TicketDetail> = {}): TicketDetail {
  const {
    description = "",
    timeline = [],
    parent = null,
    children = [],
    tasks = [],
    brief = null,
    pull_requests = [],
    ...listOverrides
  } = overrides
  return {
    ...makeTicket(listOverrides),
    description,
    timeline,
    parent,
    children,
    tasks,
    brief,
    pull_requests,
  }
}

/** The reserved human actor (memo A1). */
export const HUMAN_ACTOR: Actor = { session_id: "human", name: "human", directory: null }

/**
 * Stateful handlers for one ticket's detail page: `GET /api/tickets/:id` plus the
 * mutations the page can perform. Each mutation records its parsed JSON body, applies
 * the change to the in-memory detail, and returns the updated `TicketDetail` (A3);
 * later GETs return the same updated detail. So a page may either use the mutation
 * response or invalidate and refetch — both see the new state.
 *
 * Usage: `const ticket = statefulTicketDetail(detail); server.use(...ticket.handlers)`.
 */
export function statefulTicketDetail(initial: TicketDetail) {
  let detail = initial
  let clock = 0
  const commentRequests: CommentIn[] = []
  const statusRequests: StatusChangeIn[] = []
  const flagRequests: NeedsHumanEyesIn[] = []
  const taskRequests: TaskCreate[] = []
  const taskStateRequests: { taskId: number; body: TaskStateIn }[] = []
  /** Per-task history, keyed by task id; `GET /api/tasks/:id` joins it onto the embedded task. */
  const taskHistory = new Map<number, TaskHistoryEntry[]>()
  /** Custom statuses this "server" has seen, in first-use order (A13 lists them sorted). */
  const customStatuses: string[] = []

  const rememberCustom = (name: string) => {
    if (!BUILT_IN_STATUSES.some((s) => s.name === name) && !customStatuses.includes(name)) {
      customStatuses.push(name)
    }
  }

  /** Applies a status change by `actor`; returns false when it is a no-op (same status). */
  const applyStatus = (status: string, reason: string, actor: Actor): boolean => {
    const from = detail.status
    if (from === status) return false
    rememberCustom(status)
    const entry = makeTimelineEntry({
      kind: "status_change",
      actor,
      body:
        from === null
          ? `${actor.name} set status to ${status}`
          : `${actor.name} changed status from ${from} to ${status}`,
      from_status: from,
      to_status: status,
      reason,
      created_at: nextCreatedAt(),
    })
    detail = { ...detail, status, timeline: [...detail.timeline, entry], updated_at: entry.created_at }
    return true
  }

  const nextCreatedAt = () => {
    clock += 1
    return `2026-09-13T12:${String(clock).padStart(2, "0")}:00Z`
  }

  const FINISHED: Task["state"][] = ["done", "cancelled"]
  /** Recomputes every task's `blocked_by` from the current states, like the backend does. */
  const withBlockedBy = (tasks: Task[]): Task[] => {
    const stateOf = new Map(tasks.map((t) => [t.id, t.state]))
    return tasks.map((t) => ({
      ...t,
      blocked_by: t.depends_on.filter((id) => !FINISHED.includes(stateOf.get(id) ?? "todo")),
    }))
  }
  const taskDetail = (task: Task): TaskDetail => ({ ...task, history: taskHistory.get(task.id) ?? [] })

  const handlers = [
    http.get(`/api/tickets/${initial.id}`, () => HttpResponse.json(detail)),
    http.post(`/api/tickets/${initial.id}/tasks`, async ({ request }) => {
      const body = (await request.json()) as TaskCreate
      taskRequests.push(body)
      const task = makeTask({
        ticket_id: initial.id,
        title: body.title,
        description: body.description ?? "",
        depends_on: [...(body.depends_on ?? [])].sort((a, b) => a - b),
        created_at: nextCreatedAt(),
      })
      const tasks = withBlockedBy([...detail.tasks, task])
      detail = { ...detail, tasks, updated_at: task.created_at }
      return HttpResponse.json(taskDetail(tasks[tasks.length - 1]!), { status: 201 })
    }),
    http.get("/api/tasks/:id", ({ params }) => {
      const task = detail.tasks.find((t) => t.id === Number(params.id))
      if (task === undefined) return HttpResponse.json({ detail: "Not Found" }, { status: 404 })
      return HttpResponse.json(taskDetail(task))
    }),
    http.post("/api/tasks/:id/state", async ({ params, request }) => {
      const taskId = Number(params.id)
      const body = (await request.json()) as TaskStateIn
      taskStateRequests.push({ taskId, body })
      const task = detail.tasks.find((t) => t.id === taskId)
      if (task === undefined) return HttpResponse.json({ detail: "Not Found" }, { status: 404 })
      if (task.state === body.state) return HttpResponse.json(taskDetail(task)) // no-op
      const entry = makeTaskHistoryEntry({
        kind: "state_change",
        actor: HUMAN_ACTOR,
        body: `human changed state from ${task.state} to ${body.state}`,
        from_state: task.state,
        to_state: body.state,
        reason: body.reason ?? null,
        created_at: nextCreatedAt(),
      })
      taskHistory.set(taskId, [...(taskHistory.get(taskId) ?? []), entry])
      const tasks = withBlockedBy(
        detail.tasks.map((t) => (t.id === taskId ? { ...t, state: body.state, updated_at: entry.created_at } : t)),
      )
      detail = { ...detail, tasks, updated_at: entry.created_at }
      return HttpResponse.json(taskDetail(tasks.find((t) => t.id === taskId)!))
    }),
    http.post(`/api/tickets/${initial.id}/comments`, async ({ request }) => {
      const body = (await request.json()) as CommentIn
      commentRequests.push(body)
      const entry = makeTimelineEntry({
        kind: "comment",
        actor: HUMAN_ACTOR,
        body: body.body,
        created_at: nextCreatedAt(),
      })
      detail = { ...detail, timeline: [...detail.timeline, entry], updated_at: entry.created_at }
      return HttpResponse.json(detail)
    }),
    http.post(`/api/tickets/${initial.id}/status`, async ({ request }) => {
      const body = (await request.json()) as StatusChangeIn
      statusRequests.push(body)
      applyStatus(body.status, body.reason, HUMAN_ACTOR) // same status → no-op (B3.7)
      return HttpResponse.json(detail)
    }),
    http.post(`/api/tickets/${initial.id}/needs-human-eyes`, async ({ request }) => {
      const body = (await request.json()) as NeedsHumanEyesIn
      flagRequests.push(body)
      if (detail.needs_human_eyes === body.value) return HttpResponse.json(detail) // no-op (A6)
      const entry = makeTimelineEntry({
        kind: "flag_change",
        actor: HUMAN_ACTOR,
        body: body.value ? "human flagged needs human eyes" : "human cleared needs human eyes",
        reason: body.reason ?? null,
        created_at: nextCreatedAt(),
      })
      detail = {
        ...detail,
        needs_human_eyes: body.value,
        timeline: [...detail.timeline, entry],
        updated_at: entry.created_at,
      }
      return HttpResponse.json(detail)
    }),
  ]

  return {
    handlers,
    /** Parsed bodies of every `POST .../comments` seen, in order. */
    commentRequests,
    /** Parsed bodies of every `POST .../status` seen, in order. */
    statusRequests,
    /** Parsed bodies of every `POST .../needs-human-eyes` seen, in order. */
    flagRequests,
    /** Parsed bodies of every `POST /api/tickets/:id/tasks` seen, in order. */
    taskRequests,
    /** Every `POST /api/tasks/:id/state` seen, in order, with the task id it targeted. */
    taskStateRequests,
    /** Seeds the history `GET /api/tasks/:id` returns for one of the initial tasks. */
    seedTaskHistory: (taskId: number, entries: TaskHistoryEntry[]) => taskHistory.set(taskId, entries),
    /** The detail as the "server" currently has it. */
    current: () => detail,
    /**
     * Changes the status "from elsewhere" (a Claude session, not the UI under test), so the
     * next GET returns the new status plus its status_change entry. Use it to simulate
     * background activity the page must pick up on refetch.
     */
    setStatus: (status: string, reason = "changed elsewhere") =>
      applyStatus(status, reason, {
        session_id: "sess-1",
        name: "cool-willow",
        directory: "/home/dev/app",
      }),
    /**
     * `GET /api/statuses` that follows this "server": built-ins in canonical order, then every
     * custom status seen via the status POST or `setStatus`, sorted by name (A13).
     */
    statusesHandler: http.get("/api/statuses", () => {
      const customs: StatusItem[] = [...customStatuses]
        .sort()
        .map((name) => ({ name, is_builtin: false }))
      return HttpResponse.json([...BUILT_IN_STATUSES, ...customs])
    }),
    /**
     * `GET /api/tickets/summary` for a world containing only this ticket: the count is 1 while
     * it needs human eyes, else 0, and follows the flag mutation above.
     */
    summaryHandler: http.get("/api/tickets/summary", () => {
      const body: TicketsSummary = { needs_human_eyes_count: detail.needs_human_eyes ? 1 : 0 }
      return HttpResponse.json(body)
    }),
  }
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

/** MSW handler for `GET /api/alerts/summary` returning the given badge count. */
export function alertsSummaryHandler(undismissed_count: number) {
  return http.get("/api/alerts/summary", () => {
    const body: AlertsSummary = { undismissed_count }
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
