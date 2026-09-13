import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes } from "react-router-dom"
import { TicketDetailPage } from "@/pages/TicketDetailPage"
import {
  BUILT_IN_STATUSES,
  HUMAN_ACTOR,
  makeTicketDetail,
  makeTimelineEntry,
  statefulTicketDetail,
  statusesHandler,
  ticketDetailHandler,
} from "@/test/handlers"
import { server } from "@/test/msw"
import { renderWithProviders } from "@/test/render"

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
})
