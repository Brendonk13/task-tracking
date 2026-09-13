import { screen, within } from "@testing-library/react"
import { Route, Routes } from "react-router-dom"
import { TicketDetailPage } from "@/pages/TicketDetailPage"
import { makeTicketDetail, makeTimelineEntry, ticketDetailHandler } from "@/test/handlers"
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
})
