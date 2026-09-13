import { screen, within } from "@testing-library/react"
import { SessionsPage } from "@/pages/SessionsPage"
import { server } from "@/test/msw"
import { renderWithProviders } from "@/test/render"
import { makeSession, sessionsHandler } from "@/test/sessionHandlers"

// Layout convention: sessions render in a <table>; each session is a role="row" (plus one
// header row). Rows are looked up by their accessible name (row text), so a row must contain
// the session name, directory, last message and relative time as visible text.
//
// Relative time convention: `last_message_at` is shown relative to the current clock in the
// style of `Intl.RelativeTimeFormat("en", { numeric: "auto" })`, e.g. "2 hours ago".
//
// Empty-message convention: a session with `last_message: null` shows the literal
// "no messages yet" in place of the last message (and no relative time).
//
// Ordering convention: rows appear in exactly the order GET /api/sessions returned them;
// the server sorts by newest activity (A10) and the page never re-sorts.

// Frozen "now" for deterministic relative times. `vi.setSystemTime` only mocks `Date`
// (no fake timers), so userEvent/waitFor keep working.
const NOW = new Date("2026-09-12T12:00:00Z")

describe("SessionsPage", () => {
  beforeEach(() => {
    vi.setSystemTime(NOW)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("lists sessions with name, directory, last message and relative time", async () => {
    server.use(
      sessionsHandler([
        makeSession({
          session_id: "sess-1",
          name: "cool-willow",
          directory: "/home/dev/app",
          last_message: "Fix the login redirect",
          last_message_at: "2026-09-12T10:00:00Z", // 2 hours before NOW
        }),
        makeSession({
          session_id: "sess-2",
          name: "quiet-otter",
          directory: "/home/dev/docs",
          last_message: null,
          last_message_at: null,
        }),
      ]),
    )
    renderWithProviders(<SessionsPage />)

    await screen.findByText("cool-willow")

    const willowRow = screen.getByRole("row", { name: /cool-willow/i })
    expect(within(willowRow).getByText("/home/dev/app")).toBeInTheDocument()
    expect(within(willowRow).getByText("Fix the login redirect")).toBeInTheDocument()
    expect(within(willowRow).getByText("2 hours ago")).toBeInTheDocument()

    const otterRow = screen.getByRole("row", { name: /quiet-otter/i })
    expect(within(otterRow).getByText("/home/dev/docs")).toBeInTheDocument()
    expect(within(otterRow).getByText("no messages yet")).toBeInTheDocument()
    expect(within(otterRow).queryByText(/ago$/i)).toBeNull()

    // Header row + two session rows, nothing else.
    expect(screen.getAllByRole("row")).toHaveLength(3)
  })

  it("sessions are ordered as returned by the API (newest activity first)", async () => {
    // Deliberately neither alphabetical by name nor chronological by created_at: the only
    // thing that explains this order is "newest last_message_at first", which the server did.
    server.use(
      sessionsHandler([
        makeSession({
          session_id: "sess-b",
          name: "misty-fox",
          last_message: "Third",
          last_message_at: "2026-09-12T11:30:00Z",
          created_at: "2026-09-10T09:00:00Z",
        }),
        makeSession({
          session_id: "sess-c",
          name: "amber-lynx",
          last_message: "Second",
          last_message_at: "2026-09-12T09:00:00Z",
          created_at: "2026-09-12T08:00:00Z",
        }),
        makeSession({
          session_id: "sess-a",
          name: "zesty-crow",
          last_message: "First",
          last_message_at: "2026-09-11T20:00:00Z",
          created_at: "2026-09-11T19:00:00Z",
        }),
      ]),
    )
    renderWithProviders(<SessionsPage />)

    await screen.findByText("misty-fox")

    const [, ...sessionRows] = screen.getAllByRole("row") // drop the header row
    const namesInOrder = sessionRows.map((row) =>
      ["misty-fox", "amber-lynx", "zesty-crow"].find((name) => within(row).queryByText(name)),
    )
    expect(namesInOrder).toEqual(["misty-fox", "amber-lynx", "zesty-crow"])
  })
})
