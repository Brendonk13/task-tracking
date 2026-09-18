import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { Route, Routes } from "react-router-dom"
import type { components } from "@/api/schema.d.ts"
import { AppShell } from "@/components/layout/AppShell"
import { TicketDetailPage } from "@/pages/TicketDetailPage"
import {
  BUILT_IN_STATUSES,
  HUMAN_ACTOR,
  makeTask,
  makeTaskHistoryEntry,
  makeTicket,
  makeTicketDetail,
  makeTimelineEntry,
  recordRequests,
  statefulTicketDetail,
  statusesHandler,
  ticketDetailHandler,
} from "@/test/handlers"
import { server } from "@/test/msw"
import { renderWithProviders } from "@/test/render"

type PullRequestItem = components["schemas"]["PullRequestItem"]

// The page reads the ticket id from the `/tickets/:id` route param, so it is rendered
// inside a matching <Route>; App.tsx wiring is not under test here.
function renderDetail(id: number) {
  return renderWithProviders(
    <Routes>
      <Route path="/tickets/:id" element={<TicketDetailPage />} />
    </Routes>,
    { route: `/tickets/${id}` },
  )
}

// Header convention: the ticket title is the page's only level-1 heading. Description,
// priority, status chip, project tag and label tags are plain visible text (Badges for
// the chips/tags); tests find them with getByText, no aria-labels required.
describe("TicketDetailPage", () => {
  // The status form lists the statuses from GET /api/statuses; default to the built-ins so
  // every test has that request handled.
  beforeEach(() => {
    server.use(statusesHandler())
  })

  it("shows title, description, priority, current status, project tag and label tags", async () => {
    server.use(
      ticketDetailHandler(
        makeTicketDetail({
          id: 7,
          title: "Fix login",
          description: "Users get 500 on login",
          priority: "high",
          status: "blocked",
          project: "backend",
          labels: ["auth", "infra"],
        }),
      ),
    )
    renderDetail(7)

    expect(await screen.findByRole("heading", { level: 1, name: "Fix login" })).toBeInTheDocument()
    expect(screen.getByText("Users get 500 on login")).toBeInTheDocument()
    expect(screen.getByText(/^high$/i)).toBeInTheDocument()
    expect(screen.getByText("blocked")).toBeInTheDocument()
    expect(screen.getByText("backend")).toBeInTheDocument()
    expect(screen.getByText("auth")).toBeInTheDocument()
    expect(screen.getByText("infra")).toBeInTheDocument()
  })

  // Timeline convention: <ol aria-label="Timeline"> rendered in API order (oldest first),
  // one <li data-kind="comment|status_change|flag_change|field_change"> per entry.
  // A comment's body is a bubble: an element with role="article" inside its <li>.
  // Status changes are plain event lines (no article).
  it("renders timeline oldest first with comments and status changes styled differently", async () => {
    server.use(
      ticketDetailHandler(
        makeTicketDetail({
          id: 7,
          title: "Fix login",
          status: "planning",
          timeline: [
            makeTimelineEntry({
              id: 1,
              kind: "status_change",
              body: "cool-willow set status to blocked",
              to_status: "blocked",
              reason: "waiting on vendor",
              created_at: "2026-09-12T10:00:00Z",
            }),
            makeTimelineEntry({
              id: 2,
              kind: "comment",
              body: "Pinged the vendor",
              created_at: "2026-09-12T10:05:00Z",
            }),
            makeTimelineEntry({
              id: 3,
              kind: "status_change",
              body: "cool-willow changed status from blocked to planning",
              from_status: "blocked",
              to_status: "planning",
              reason: "vendor replied",
              created_at: "2026-09-12T10:10:00Z",
            }),
          ],
        }),
      ),
    )
    renderDetail(7)

    const timeline = await screen.findByRole("list", { name: /timeline/i })
    const items = within(timeline).getAllByRole("listitem")
    expect(items).toHaveLength(3)

    // Oldest first, as returned by the API.
    expect(items[0]).toHaveTextContent("cool-willow set status to blocked")
    expect(items[1]).toHaveTextContent("Pinged the vendor")
    expect(items[2]).toHaveTextContent("cool-willow changed status from blocked to planning")

    // Each entry is marked with its kind, and only comments render as a bubble.
    expect(items[0]).toHaveAttribute("data-kind", "status_change")
    expect(items[1]).toHaveAttribute("data-kind", "comment")
    expect(items[2]).toHaveAttribute("data-kind", "status_change")
    expect(within(items[1]!).getByRole("article")).toHaveTextContent("Pinged the vendor")
    expect(within(items[0]!).queryByRole("article")).toBeNull()
    expect(within(items[2]!).queryByRole("article")).toBeNull()
  })

  // Reason convention: a status change's `reason` is rendered as its own element inside the
  // <li>, whose text is exactly the reason string (any "Reason" label lives in a sibling).
  it('status change event reads "<name> changed status from X to Y" and shows the reason; first-ever change reads "<name> set status to Y"', async () => {
    server.use(
      ticketDetailHandler(
        makeTicketDetail({
          id: 7,
          title: "Fix login",
          status: "planning",
          timeline: [
            makeTimelineEntry({
              id: 1,
              kind: "status_change",
              body: "cool-willow set status to blocked",
              from_status: null,
              to_status: "blocked",
              reason: "waiting on vendor",
              created_at: "2026-09-12T10:00:00Z",
            }),
            makeTimelineEntry({
              id: 2,
              kind: "status_change",
              body: "cool-willow changed status from blocked to planning",
              from_status: "blocked",
              to_status: "planning",
              reason: "vendor replied",
              created_at: "2026-09-12T10:10:00Z",
            }),
          ],
        }),
      ),
    )
    renderDetail(7)

    const timeline = await screen.findByRole("list", { name: /timeline/i })
    const [first, second] = within(timeline).getAllByRole("listitem")

    expect(first).toHaveTextContent("cool-willow set status to blocked")
    expect(within(first!).getByText("waiting on vendor")).toBeVisible()

    expect(second).toHaveTextContent("cool-willow changed status from blocked to planning")
    expect(within(second!).getByText("vendor replied")).toBeVisible()
  })

  // Actor convention: every <li> shows the actor's session name in an element marked
  // data-slot="timeline-actor" (separate from the body, which may also contain the name).
  // The human actor renders as "human".
  it("each timeline entry shows the actor session name", async () => {
    const actor = { selector: "[data-slot='timeline-actor']" }
    server.use(
      ticketDetailHandler(
        makeTicketDetail({
          id: 7,
          title: "Fix login",
          status: "blocked",
          timeline: [
            makeTimelineEntry({
              id: 1,
              kind: "comment",
              actor: { session_id: "sess-1", name: "cool-willow", directory: "/home/dev/app" },
              body: "Looking into it",
              created_at: "2026-09-12T10:00:00Z",
            }),
            makeTimelineEntry({
              id: 2,
              kind: "status_change",
              actor: { session_id: "sess-2", name: "brave-otter", directory: "/home/dev/other" },
              body: "brave-otter set status to blocked",
              to_status: "blocked",
              reason: "repro found",
              created_at: "2026-09-12T10:05:00Z",
            }),
            makeTimelineEntry({
              id: 3,
              kind: "comment",
              actor: { session_id: "human", name: "human", directory: null },
              body: "Thanks, taking over",
              created_at: "2026-09-12T10:10:00Z",
            }),
          ],
        }),
      ),
    )
    renderDetail(7)

    const timeline = await screen.findByRole("list", { name: /timeline/i })
    const items = within(timeline).getAllByRole("listitem")
    expect(items).toHaveLength(3)

    expect(within(items[0]!).getByText("cool-willow", actor)).toBeVisible()
    expect(within(items[1]!).getByText("brave-otter", actor)).toBeVisible()
    expect(within(items[2]!).getByText("human", actor)).toBeVisible()
  })

  // Resume convention: an entry whose actor has a directory shows a button whose accessible
  // name matches /resume session/i (suggested: "Resume session <name>"). Clicking it writes
  // `cd <directory> && claude --resume <session_id>` to the clipboard. Entries whose actor
  // has `directory: null` (the human actor) render no such button (memo A1).
  // Clipboard: userEvent.setup() installs a navigator.clipboard stub; the test reads it back.
  it('resume-session button on an entry copies "cd <dir> && claude --resume <id>" to clipboard', async () => {
    const user = userEvent.setup()
    server.use(
      ticketDetailHandler(
        makeTicketDetail({
          id: 7,
          title: "Fix login",
          timeline: [
            makeTimelineEntry({
              id: 1,
              kind: "comment",
              actor: { session_id: "sess-42", name: "cool-willow", directory: "/home/dev/app" },
              body: "Looking into it",
              created_at: "2026-09-12T10:00:00Z",
            }),
            makeTimelineEntry({
              id: 2,
              kind: "comment",
              actor: HUMAN_ACTOR,
              body: "Thanks, taking over",
              created_at: "2026-09-12T10:05:00Z",
            }),
          ],
        }),
      ),
    )
    renderDetail(7)

    const timeline = await screen.findByRole("list", { name: /timeline/i })
    const [bySession, byHuman] = within(timeline).getAllByRole("listitem")

    await user.click(within(bySession!).getByRole("button", { name: /resume session/i }))
    expect(await navigator.clipboard.readText()).toBe("cd /home/dev/app && claude --resume sess-42")

    expect(within(byHuman!).queryByRole("button", { name: /resume/i })).toBeNull()
  })

  // Comment form convention: a textbox with accessible name matching /comment/i and a submit
  // button named /post comment/i. Posting sends {body, actor_session_id: "human"}, the new
  // entry appears at the end of the timeline, and the textbox is cleared.
  it('human can post a comment; request carries actor_session_id "human" and timeline refreshes', async () => {
    const user = userEvent.setup()
    const ticket = statefulTicketDetail(
      makeTicketDetail({
        id: 7,
        title: "Fix login",
        timeline: [
          makeTimelineEntry({
            id: 1,
            kind: "comment",
            body: "Looking into it",
            created_at: "2026-09-12T10:00:00Z",
          }),
        ],
      }),
    )
    server.use(...ticket.handlers)
    renderDetail(7)

    const timeline = await screen.findByRole("list", { name: /timeline/i })
    expect(within(timeline).getAllByRole("listitem")).toHaveLength(1)

    const box = screen.getByRole("textbox", { name: /comment/i })
    await user.type(box, "Looks good")
    await user.click(screen.getByRole("button", { name: /post comment/i }))

    await waitFor(() =>
      expect(ticket.commentRequests).toEqual([{ body: "Looks good", actor_session_id: "human" }]),
    )

    // The timeline shows the new comment as its newest entry, by the human actor.
    await waitFor(() =>
      expect(within(screen.getByRole("list", { name: /timeline/i })).getAllByRole("listitem")).toHaveLength(2),
    )
    const [, posted] = within(screen.getByRole("list", { name: /timeline/i })).getAllByRole("listitem")
    expect(posted).toHaveAttribute("data-kind", "comment")
    expect(within(posted!).getByRole("article")).toHaveTextContent("Looks good")
    expect(within(posted!).getByText("human", { selector: "[data-slot='timeline-actor']" })).toBeVisible()

    expect(screen.getByRole("textbox", { name: /comment/i })).toHaveValue("")
  })

  // Status form convention: a native <select> with accessible name "Status" whose <option>s are
  // the names from GET /api/statuses (built-ins then customs, option text = value = name), plus
  // a final "Other…" option that reveals a textbox named "New status" for typing a brand-new
  // one (not exercised here). A textbox named "Reason" (must not match /comment/i) and a button
  // "Change status". Submitting posts {status, reason, actor_session_id: "human"}.
  // The header's current-status chip is a Badge: getByText(name, { selector: "[data-slot='badge']" }).
  it('human can change status via a select + reason field; request carries {status, reason, actor_session_id:"human"}', async () => {
    const user = userEvent.setup()
    const ticket = statefulTicketDetail(
      makeTicketDetail({ id: 7, title: "Fix login", status: "blocked", timeline: [] }),
    )
    server.use(
      ...ticket.handlers,
      statusesHandler([...BUILT_IN_STATUSES, { name: "waiting-on-vendor", is_builtin: false }]),
    )
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Fix login" })
    expect(screen.getByText("blocked", { selector: "[data-slot='badge']" })).toBeInTheDocument()

    // Built-ins and customs from /api/statuses are both offered.
    const select = await screen.findByRole("combobox", { name: /^status$/i })
    expect(within(select).getByRole("option", { name: "blocked" })).toBeInTheDocument()
    expect(within(select).getByRole("option", { name: "waiting-on-vendor" })).toBeInTheDocument()

    await user.selectOptions(select, "waiting-on-vendor")
    await user.type(screen.getByRole("textbox", { name: /reason/i }), "vendor replied")
    await user.click(screen.getByRole("button", { name: /change status/i }))

    await waitFor(() =>
      expect(ticket.statusRequests).toEqual([
        { status: "waiting-on-vendor", reason: "vendor replied", actor_session_id: "human" },
      ]),
    )

    // The header chip and the timeline both reflect the change.
    expect(
      await screen.findByText("waiting-on-vendor", { selector: "[data-slot='badge']" }),
    ).toBeInTheDocument()
    const timeline = screen.getByRole("list", { name: /timeline/i })
    const [event] = within(timeline).getAllByRole("listitem")
    expect(event).toHaveAttribute("data-kind", "status_change")
    expect(event).toHaveTextContent("human changed status from blocked to waiting-on-vendor")
    expect(within(event!).getByText("vendor replied")).toBeVisible()
  })

  // Flag convention: a role="switch" named "Needs human eyes" in the header, checked iff
  // ticket.needs_human_eyes. Toggling posts {value, actor_session_id: "human"} (reason optional).
  it("human can toggle needs human eyes", async () => {
    const user = userEvent.setup()
    const ticket = statefulTicketDetail(
      makeTicketDetail({ id: 7, title: "Fix login", needs_human_eyes: false, timeline: [] }),
    )
    server.use(...ticket.handlers)
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Fix login" })
    const toggle = screen.getByRole("switch", { name: /needs human eyes/i })
    expect(toggle).not.toBeChecked()

    await user.click(toggle)

    await waitFor(() => expect(ticket.flagRequests).toHaveLength(1))
    expect(ticket.flagRequests[0]).toMatchObject({ value: true, actor_session_id: "human" })

    await waitFor(() =>
      expect(screen.getByRole("switch", { name: /needs human eyes/i })).toBeChecked(),
    )
    const timeline = screen.getByRole("list", { name: /timeline/i })
    const [event] = within(timeline).getAllByRole("listitem")
    expect(event).toHaveAttribute("data-kind", "flag_change")
    expect(event).toHaveTextContent("human flagged needs human eyes")
  })

  // Linear convention: when `linear_url` is set, the header shows an anchor with visible text
  // "Open in Linear" (accessible name matches /linear/i), href = the URL verbatim,
  // target="_blank", rel including "noopener". When null, no such link is rendered at all.
  it("linear url renders as an external link when present", async () => {
    server.use(
      ticketDetailHandler(
        makeTicketDetail({
          id: 7,
          title: "Fix login",
          linear_url: "https://linear.app/acme/issue/ENG-123",
        }),
      ),
      ticketDetailHandler(makeTicketDetail({ id: 8, title: "Write docs", linear_url: null })),
    )

    const withUrl = renderDetail(7)
    await screen.findByRole("heading", { level: 1, name: "Fix login" })

    const link = screen.getByRole("link", { name: /linear/i })
    expect(link).toHaveAttribute("href", "https://linear.app/acme/issue/ENG-123")
    expect(link).toHaveAttribute("target", "_blank")
    expect(link.getAttribute("rel")).toMatch(/\bnoopener\b/)

    withUrl.unmount()

    renderDetail(8)
    await screen.findByRole("heading", { level: 1, name: "Write docs" })
    expect(screen.queryByRole("link", { name: /linear/i })).toBeNull()
  })

  // Brief convention: when the ticket has a `brief`, the header shows an anchor beside the
  // Linear link whose accessible name matches /brief/i (suggested text "Open brief"), with
  // href="/api/tickets/{id}/brief" and target="_blank" so the HTML opens in a new tab. A
  // ticket with `brief: null` renders no such link.
  it("shows an open-brief link to /api/tickets/{id}/brief when the ticket has a brief and nothing otherwise", async () => {
    server.use(
      ticketDetailHandler(
        makeTicketDetail({
          id: 7,
          title: "Fix login",
          brief: {
            md_path: "/home/dev/ticket-briefs/2026-09-17-CON-7.md",
            html_path: "/home/dev/ticket-briefs/2026-09-17-CON-7.html",
          },
        }),
      ),
      ticketDetailHandler(makeTicketDetail({ id: 8, title: "Write docs", brief: null })),
    )

    const withBrief = renderDetail(7)
    await screen.findByRole("heading", { level: 1, name: "Fix login" })

    const link = screen.getByRole("link", { name: /brief/i })
    expect(link).toHaveAttribute("href", "/api/tickets/7/brief")
    expect(link).toHaveAttribute("target", "_blank")

    withBrief.unmount()

    renderDetail(8)
    await screen.findByRole("heading", { level: 1, name: "Write docs" })
    expect(screen.queryByRole("link", { name: /brief/i })).toBeNull()
  })

  // Pull-request convention: when the ticket has PRs, a "Pull requests" section renders
  // <ul aria-label="Pull requests">, one <li> per entry in API order. Each row shows an
  // external anchor named "#<number>" (href = pr.url verbatim, target="_blank", rel with
  // noopener), the PR state, how many comments it has ("<n> comments") and the name of the
  // session that last triaged it, marked data-slot="pr-triage-session" (the same shape as
  // timeline-actor); a PR nobody has triaged shows no session name. `TicketDetail.pull_requests`
  // (schemas.TicketPullRequest) carries only {id, number, url, state}, so the count and the
  // triage session come from GET /api/pull-requests, matched on the PR id — exactly the join
  // AlertsPage already does. That request is only worth making when the ticket has PRs, so a
  // ticket with `pull_requests: []` must not fire it (every other test here would otherwise
  // need a new handler under MSW's onUnhandledRequest: "error"); it shows "No pull requests."
  // instead. If the backend ever grows these fields on TicketPullRequest, the handler can go
  // away and the assertions stay exactly as they are.
  it("lists pull requests with number, state, comment count and last triage session", async () => {
    const pullRequest = (
      overrides: Partial<PullRequestItem> & { id: number; number: number },
    ): PullRequestItem => ({
      repo: "mosaic-avantos/avantos",
      url: `https://github.com/mosaic-avantos/avantos/pull/${overrides.number}`,
      title: `Pull request ${overrides.number}`,
      branch: `brendonkeirle/con-${overrides.number}`,
      head_sha: "0f1e2d3",
      state: "open",
      author: "Brendonk13",
      ticket_id: 7,
      comment_count: 0,
      last_triage_session: null,
      ...overrides,
    })

    server.use(
      ticketDetailHandler(
        makeTicketDetail({
          id: 7,
          title: "Fix login",
          pull_requests: [
            {
              id: 101,
              number: 42,
              url: "https://github.com/mosaic-avantos/avantos/pull/42",
              state: "merged",
            },
            {
              id: 102,
              number: 43,
              url: "https://github.com/mosaic-avantos/avantos/pull/43",
              state: "open",
            },
          ],
        }),
      ),
      ticketDetailHandler(makeTicketDetail({ id: 8, title: "Write docs", pull_requests: [] })),
      http.get("/api/pull-requests", () =>
        HttpResponse.json([
          pullRequest({
            id: 101,
            number: 42,
            state: "merged",
            comment_count: 3,
            last_triage_session: {
              session_id: "sess-9",
              name: "cool-willow",
              directory: "/home/dev/app",
            },
          }),
          pullRequest({ id: 102, number: 43 }),
        ]),
      ),
    )

    const withPrs = renderDetail(7)
    await screen.findByRole("heading", { level: 1, name: "Fix login" })

    const list = await screen.findByRole("list", { name: /^pull requests$/i })
    const rows = within(list).getAllByRole("listitem")
    expect(rows).toHaveLength(2)

    const link = within(rows[0]!).getByRole("link", { name: /#42/ })
    expect(link).toHaveAttribute("href", "https://github.com/mosaic-avantos/avantos/pull/42")
    expect(link).toHaveAttribute("target", "_blank")
    expect(link.getAttribute("rel")).toMatch(/\bnoopener\b/)
    expect(rows[0]).toHaveTextContent("merged")
    expect(rows[0]).toHaveTextContent(/3 comments/i)
    expect(
      within(rows[0]!).getByText("cool-willow", { selector: "[data-slot='pr-triage-session']" }),
    ).toBeVisible()

    expect(within(rows[1]!).getByRole("link", { name: /#43/ })).toHaveAttribute(
      "href",
      "https://github.com/mosaic-avantos/avantos/pull/43",
    )
    expect(rows[1]).toHaveTextContent("open")
    expect(rows[1]).toHaveTextContent(/0 comments/i)
    expect(within(rows[1]!).queryByText("cool-willow")).toBeNull()
    expect(screen.queryByText("No pull requests.")).toBeNull()

    withPrs.unmount()

    renderDetail(8)
    await screen.findByRole("heading", { level: 1, name: "Write docs" })
    expect(await screen.findByText("No pull requests.")).toBeInTheDocument()
    expect(screen.queryByRole("list", { name: /^pull requests$/i })).toBeNull()
  })

  // ---- Reviewer pins (end of F3/F4) ----

  it("flagging needs human eyes from the detail page updates the sidebar badge", async () => {
    const user = userEvent.setup()
    const requests = recordRequests()
    const ticket = statefulTicketDetail(
      makeTicketDetail({ id: 7, title: "Fix login", needs_human_eyes: false, timeline: [] }),
    )
    server.use(...ticket.handlers, ticket.summaryHandler)
    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="tickets/:id" element={<TicketDetailPage />} />
        </Route>
      </Routes>,
      { route: "/tickets/7" },
    )

    await screen.findByRole("heading", { level: 1, name: "Fix login" })
    // Settled zero: the summary has been fetched and there is no badge.
    await waitFor(() => expect(requests).toContain("/api/tickets/summary"))
    const nav = screen.getByRole("navigation")
    expect(within(nav).queryByRole("status")).toBeNull()

    await user.click(screen.getByRole("switch", { name: /needs human eyes/i }))

    expect(
      await within(nav).findByRole("status", { name: /1 ticket needs human eyes/i }),
    ).toHaveTextContent("1")
  })

  it("human can type a new status via the Other option", async () => {
    const user = userEvent.setup()
    const ticket = statefulTicketDetail(
      makeTicketDetail({ id: 7, title: "Fix login", status: "blocked", timeline: [] }),
    )
    // Stateful statuses: after the POST, GET /api/statuses lists the new custom status.
    server.use(...ticket.handlers, ticket.statusesHandler)
    renderDetail(7)

    const select = await screen.findByRole("combobox", { name: /^status$/i })
    await user.selectOptions(select, within(select).getByRole("option", { name: /^other/i }))
    await user.type(screen.getByRole("textbox", { name: /new status/i }), "waiting-on-vendor")
    await user.type(screen.getByRole("textbox", { name: /reason/i }), "vendor replied")
    await user.click(screen.getByRole("button", { name: /change status/i }))

    await waitFor(() =>
      expect(ticket.statusRequests).toEqual([
        { status: "waiting-on-vendor", reason: "vendor replied", actor_session_id: "human" },
      ]),
    )
    expect(
      await screen.findByText("waiting-on-vendor", { selector: "[data-slot='badge']" }),
    ).toBeInTheDocument()

    // The new custom status is now a real option and the select shows it as current.
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: /^status$/i })).toHaveValue("waiting-on-vendor"),
    )
    expect(
      within(screen.getByRole("combobox", { name: /^status$/i })).getByRole("option", {
        name: "waiting-on-vendor",
      }),
    ).toBeInTheDocument()
  })

  it("a failed comment post shows an error and keeps the draft", async () => {
    const user = userEvent.setup()
    server.use(
      http.post("/api/tickets/7/comments", () =>
        HttpResponse.json({ detail: "unknown actor" }, { status: 400 }),
      ),
      ticketDetailHandler(makeTicketDetail({ id: 7, title: "Fix login", timeline: [] })),
    )
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Fix login" })
    await user.type(screen.getByRole("textbox", { name: /comment/i }), "Looks good")
    await user.click(screen.getByRole("button", { name: /post comment/i }))

    const alert = await screen.findByRole("alert")
    expect(alert.textContent?.trim()).not.toBe("")
    expect(screen.getByRole("textbox", { name: /comment/i })).toHaveValue("Looks good")
  })

  it("focus returns to the comment box after posting", async () => {
    const user = userEvent.setup()
    const ticket = statefulTicketDetail(
      makeTicketDetail({ id: 7, title: "Fix login", timeline: [] }),
    )
    server.use(...ticket.handlers)
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Fix login" })
    await user.type(screen.getByRole("textbox", { name: /comment/i }), "Looks good")
    await user.click(screen.getByRole("button", { name: /post comment/i }))

    // Post completed and the form reset...
    await waitFor(() => expect(ticket.commentRequests).toHaveLength(1))
    await waitFor(() => expect(screen.getByRole("textbox", { name: /comment/i })).toHaveValue(""))
    // ...and the keyboard user is back in the box, ready for the next comment.
    await waitFor(() => expect(screen.getByRole("textbox", { name: /comment/i })).toHaveFocus())
  })

  // A background refetch (window focus, invalidation after another mutation, polling) is
  // simulated by invalidating the detail query on the test's QueryClient — the same code path
  // react-query's refetchOnWindowFocus takes, without relying on jsdom visibility events.
  it("status select follows the ticket when a background refetch changes the status", async () => {
    const ticket = statefulTicketDetail(
      makeTicketDetail({ id: 7, title: "Fix login", status: "blocked", timeline: [] }),
    )
    server.use(...ticket.handlers)
    const { queryClient } = renderWithProviders(
      <Routes>
        <Route path="/tickets/:id" element={<TicketDetailPage />} />
      </Routes>,
      { route: "/tickets/7" },
    )

    await screen.findByRole("heading", { level: 1, name: "Fix login" })
    // Options arrive from /api/statuses separately, so wait for the select to settle on "blocked".
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: /^status$/i })).toHaveValue("blocked"),
    )

    // A Claude session moves the ticket on; the page refetches.
    ticket.setStatus("planning", "starting work")
    await queryClient.invalidateQueries({ queryKey: ["tickets", "detail", 7] })

    expect(
      await screen.findByText("planning", { selector: "[data-slot='badge']" }),
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: /^status$/i })).toHaveValue("planning"),
    )
  })

  // Empty-timeline convention: the text "No activity yet." replaces (or accompanies an empty)
  // Timeline list when the ticket has no entries.
  it("shows an empty timeline message when there is no activity", async () => {
    server.use(ticketDetailHandler(makeTicketDetail({ id: 7, title: "Fix login", timeline: [] })))
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Fix login" })
    expect(await screen.findByText("No activity yet.")).toBeInTheDocument()

    const timeline = screen.queryByRole("list", { name: /timeline/i })
    if (timeline !== null) expect(within(timeline).queryAllByRole("listitem")).toHaveLength(0)
  })

  // Parent/child convention: a sub-ticket says "Sub-ticket of <parent title>" above the
  // heading; a parent lists its children in a "Sub-tickets" list. Both link to the detail
  // page of the other ticket. A ticket with neither shows no sub-ticket UI at all.
  it("links to the parent when the ticket is a sub-ticket", async () => {
    server.use(
      ticketDetailHandler(
        makeTicketDetail({
          id: 7,
          title: "Write the migration",
          parent_id: 3,
          parent: { id: 3, title: "Ship auth" },
        }),
      ),
    )
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Write the migration" })
    expect(screen.getByText(/sub-ticket of/i)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Ship auth" })).toHaveAttribute(
      "href",
      "/tickets/3",
    )
    expect(screen.queryByRole("list", { name: /sub-tickets/i })).not.toBeInTheDocument()
  })

  it("lists the sub-tickets with their status and flags them when they need human eyes", async () => {
    server.use(
      ticketDetailHandler(
        makeTicketDetail({
          id: 3,
          title: "Ship auth",
          children: [
            makeTicket({ id: 7, title: "Write the migration", status: "blocked" }),
            makeTicket({ id: 8, title: "Wire the frontend", needs_human_eyes: true }),
          ],
        }),
      ),
    )
    renderDetail(3)

    await screen.findByRole("heading", { level: 1, name: "Ship auth" })
    const subTickets = screen.getByRole("list", { name: /sub-tickets/i })
    const rows = within(subTickets).getAllByRole("listitem")
    expect(rows).toHaveLength(2)

    expect(within(rows[0]).getByRole("link", { name: "Write the migration" })).toHaveAttribute(
      "href",
      "/tickets/7",
    )
    expect(within(rows[0]).getByText("blocked")).toBeInTheDocument()
    expect(within(rows[0]).queryByLabelText(/needs human eyes/i)).not.toBeInTheDocument()
    expect(within(rows[1]).getByLabelText(/needs human eyes/i)).toBeInTheDocument()
    expect(screen.queryByText(/sub-ticket of/i)).not.toBeInTheDocument()
  })

  it("shows no sub-ticket UI for a standalone ticket", async () => {
    server.use(ticketDetailHandler(makeTicketDetail({ id: 7, title: "Fix login" })))
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Fix login" })
    expect(screen.queryByText(/sub-ticket of/i)).not.toBeInTheDocument()
    expect(screen.queryByRole("list", { name: /sub-tickets/i })).not.toBeInTheDocument()
  })
})

// Tasks convention: a "Tasks" section with <ul aria-label="Tasks">, one <li data-state=...
// data-blocked=...> per task, oldest first. Each row shows the title (a button that toggles the
// task's history), a state chip, a "blocked" badge when `blocked_by` is non-empty, and a
// <select aria-label="State of <title>"> for the human to change the state. "No tasks yet."
// replaces the list when empty. The add form is a textbox "New task", an optional multi-select
// "Depends on" (only when the ticket already has tasks) and a button "Add task".
describe("TicketDetailPage tasks", () => {
  beforeEach(() => {
    server.use(statusesHandler())
  })

  it("lists the tasks with their state, dependencies and blocked badge", async () => {
    server.use(
      ticketDetailHandler(
        makeTicketDetail({
          id: 7,
          title: "Ship tasks",
          tasks: [
            makeTask({ id: 1, ticket_id: 7, title: "Write the migration", state: "in_progress" }),
            makeTask({
              id: 2,
              ticket_id: 7,
              title: "Expose the API",
              depends_on: [1],
              blocked_by: [1],
            }),
            makeTask({ id: 3, ticket_id: 7, title: "Write docs", state: "done" }),
          ],
        }),
      ),
    )
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Ship tasks" })
    const list = screen.getByRole("list", { name: /^tasks$/i })
    const rows = within(list).getAllByRole("listitem")
    expect(rows).toHaveLength(3)

    expect(rows[0]).toHaveAttribute("data-state", "in_progress")
    expect(rows[0]).toHaveAttribute("data-blocked", "false")
    expect(within(rows[0]!).getByText("in progress", { selector: "[data-slot='badge']" })).toBeVisible()
    expect(within(rows[0]!).queryByText("blocked")).toBeNull()

    expect(rows[1]).toHaveAttribute("data-blocked", "true")
    expect(within(rows[1]!).getByText("blocked", { selector: "[data-slot='badge']" })).toBeVisible()
    expect(rows[1]).toHaveTextContent(/depends on:\s*Write the migration/i)

    expect(rows[2]).toHaveAttribute("data-state", "done")
    expect(within(rows[2]!).getByRole("combobox", { name: "State of Write docs" })).toHaveValue("done")
    expect(screen.queryByText("No tasks yet.")).toBeNull()
  })

  it("shows an empty message and no dependency picker when the ticket has no tasks", async () => {
    server.use(ticketDetailHandler(makeTicketDetail({ id: 7, title: "Fix login" })))
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Fix login" })
    expect(screen.getByText("No tasks yet.")).toBeInTheDocument()
    expect(screen.queryByRole("list", { name: /^tasks$/i })).toBeNull()
    expect(screen.getByRole("textbox", { name: /new task/i })).toBeInTheDocument()
    expect(screen.queryByRole("listbox", { name: /depends on/i })).toBeNull()
  })

  it('human can add a task with dependencies; request carries {title, depends_on, actor_session_id:"human"} and the list refreshes', async () => {
    const user = userEvent.setup()
    const ticket = statefulTicketDetail(
      makeTicketDetail({
        id: 7,
        title: "Ship tasks",
        tasks: [makeTask({ id: 1, ticket_id: 7, title: "Write the migration" })],
      }),
    )
    server.use(...ticket.handlers)
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Ship tasks" })
    await user.type(screen.getByRole("textbox", { name: /new task/i }), "Expose the API")
    await user.selectOptions(screen.getByRole("listbox", { name: /depends on/i }), "1")
    await user.click(screen.getByRole("button", { name: /add task/i }))

    await waitFor(() =>
      expect(ticket.taskRequests).toEqual([
        { title: "Expose the API", depends_on: [1], actor_session_id: "human" },
      ]),
    )

    const list = await screen.findByRole("list", { name: /^tasks$/i })
    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(2))
    const [, added] = within(list).getAllByRole("listitem")
    expect(added).toHaveTextContent("Expose the API")
    expect(added).toHaveAttribute("data-blocked", "true")
    expect(screen.getByRole("textbox", { name: /new task/i })).toHaveValue("")
  })

  it("human can change a task's state; dependents unblock when it is done", async () => {
    const user = userEvent.setup()
    const ticket = statefulTicketDetail(
      makeTicketDetail({
        id: 7,
        title: "Ship tasks",
        tasks: [
          makeTask({ id: 1, ticket_id: 7, title: "Write the migration" }),
          makeTask({ id: 2, ticket_id: 7, title: "Expose the API", depends_on: [1], blocked_by: [1] }),
        ],
      }),
    )
    server.use(...ticket.handlers)
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Ship tasks" })
    await user.selectOptions(
      screen.getByRole("combobox", { name: "State of Write the migration" }),
      "done",
    )

    await waitFor(() =>
      expect(ticket.taskStateRequests).toEqual([
        { taskId: 1, body: { state: "done", actor_session_id: "human" } },
      ]),
    )
    const list = screen.getByRole("list", { name: /^tasks$/i })
    await waitFor(() => {
      const [first, second] = within(list).getAllByRole("listitem")
      expect(first).toHaveAttribute("data-state", "done")
      expect(second).toHaveAttribute("data-blocked", "false")
    })
  })

  // History convention: clicking the task title toggles an <ol aria-label="History of <title>">
  // loaded from GET /api/tasks/:id, one <li data-kind=...> per entry with the actor in
  // data-slot="history-actor", the body, and the reason when present. "No changes yet." when empty.
  it("expanding a task loads and shows its history", async () => {
    const user = userEvent.setup()
    const requests = recordRequests()
    const ticket = statefulTicketDetail(
      makeTicketDetail({
        id: 7,
        title: "Ship tasks",
        tasks: [makeTask({ id: 1, ticket_id: 7, title: "Write the migration", state: "done" })],
      }),
    )
    ticket.seedTaskHistory(1, [
      makeTaskHistoryEntry({
        id: 1,
        body: "cool-willow changed state from todo to in_progress",
        reason: "starting",
        created_at: "2026-09-12T10:00:00Z",
      }),
      makeTaskHistoryEntry({
        id: 2,
        actor: HUMAN_ACTOR,
        body: "human changed state from in_progress to done",
        from_state: "in_progress",
        to_state: "done",
        created_at: "2026-09-12T10:05:00Z",
      }),
    ])
    server.use(...ticket.handlers)
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Ship tasks" })
    expect(requests).not.toContain("/api/tasks/1")
    expect(screen.queryByRole("list", { name: /history of/i })).toBeNull()

    await user.click(screen.getByRole("button", { name: /write the migration/i }))

    const history = await screen.findByRole("list", { name: "History of Write the migration" })
    const items = within(history).getAllByRole("listitem")
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveAttribute("data-kind", "state_change")
    expect(items[0]).toHaveTextContent("cool-willow changed state from todo to in_progress")
    expect(within(items[0]!).getByText("starting")).toBeVisible()
    expect(within(items[1]!).getByText("human", { selector: "[data-slot='history-actor']" })).toBeVisible()

    await user.click(screen.getByRole("button", { name: /write the migration/i }))
    expect(screen.queryByRole("list", { name: /history of/i })).toBeNull()
  })

  it("a failed task add shows an error and keeps the draft", async () => {
    const user = userEvent.setup()
    server.use(
      http.post("/api/tickets/7/tasks", () =>
        HttpResponse.json({ detail: "unknown actor" }, { status: 400 }),
      ),
      ticketDetailHandler(makeTicketDetail({ id: 7, title: "Fix login" })),
    )
    renderDetail(7)

    await screen.findByRole("heading", { level: 1, name: "Fix login" })
    await user.type(screen.getByRole("textbox", { name: /new task/i }), "Expose the API")
    await user.click(screen.getByRole("button", { name: /add task/i }))

    const alert = await screen.findByRole("alert")
    expect(alert.textContent?.trim()).not.toBe("")
    expect(screen.getByRole("textbox", { name: /new task/i })).toHaveValue("Expose the API")
  })
})
