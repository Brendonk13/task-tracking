import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AppShell } from "@/components/layout/AppShell"
import { recordRequests, summaryHandler } from "@/test/handlers"
import { server } from "@/test/msw"
import { renderWithProviders } from "@/test/render"

// Icon convention for the sidebar: lucide-react icons, which render as
// <svg aria-hidden="true">. A nav link "shows an icon" when it contains an <svg>.
describe("AppShell", () => {
  // The sidebar fetches the tickets summary for its badge; default to "nothing flagged"
  // so tests that don't care about the badge still have the request handled.
  beforeEach(() => {
    server.use(summaryHandler(0))
  })

  it("renders sidebar with Tickets and Sessions links showing icon and label", () => {
    renderWithProviders(<AppShell />)

    const nav = screen.getByRole("navigation")

    const tickets = within(nav).getByRole("link", { name: /tickets/i })
    expect(tickets).toHaveAttribute("href", "/")
    expect(tickets).toHaveTextContent("Tickets")
    expect(tickets.querySelector("svg")).not.toBeNull()

    const sessions = within(nav).getByRole("link", { name: /sessions/i })
    expect(sessions).toHaveAttribute("href", "/sessions")
    expect(sessions).toHaveTextContent("Sessions")
    expect(sessions.querySelector("svg")).not.toBeNull()
  })

  it("collapsing the sidebar hides labels but keeps icons", async () => {
    const user = userEvent.setup()
    renderWithProviders(<AppShell />)

    const nav = screen.getByRole("navigation")
    const toggle = screen.getByRole("button", { name: /collapse sidebar/i })

    await user.click(toggle)

    // Visible label text is gone from the nav...
    expect(within(nav).queryByText("Tickets")).toBeNull()
    expect(within(nav).queryByText("Sessions")).toBeNull()

    // ...but the links keep their accessible names and their icons.
    const tickets = within(nav).getByRole("link", { name: /tickets/i })
    expect(tickets).toHaveAttribute("href", "/")
    expect(tickets.querySelector("svg")).not.toBeNull()

    const sessions = within(nav).getByRole("link", { name: /sessions/i })
    expect(sessions).toHaveAttribute("href", "/sessions")
    expect(sessions.querySelector("svg")).not.toBeNull()

    // The toggle now offers to expand again.
    expect(screen.getByRole("button", { name: /expand sidebar/i })).toBeInTheDocument()
  })

  // Badge convention: <span role="status" aria-label="3 tickets need human eyes">3</span>
  it("tickets nav item shows red badge with needs-human-eyes count from summary", async () => {
    server.use(summaryHandler(3))
    renderWithProviders(<AppShell />)

    const nav = screen.getByRole("navigation")
    const tickets = within(nav).getByRole("link", { name: /tickets/i })

    const badge = await within(tickets).findByText("3")
    expect(badge).toHaveAttribute("role", "status")
    expect(badge).toHaveAccessibleName(/3 tickets need human eyes/i)
  })

  it("badge is hidden when count is zero", async () => {
    server.use(summaryHandler(0))
    const requests = recordRequests()
    renderWithProviders(<AppShell />)

    const nav = screen.getByRole("navigation")
    const tickets = within(nav).getByRole("link", { name: /tickets/i })

    // Wait until the summary has actually been requested, so the "no badge"
    // assertion is about a settled zero, not a not-yet-loaded state.
    await waitFor(() => expect(requests).toContain("/api/tickets/summary"))
    await waitFor(() => expect(within(tickets).queryByRole("status")).toBeNull())
    expect(within(tickets).queryByText("0")).toBeNull()
  })
})
