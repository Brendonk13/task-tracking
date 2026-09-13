import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AppShell } from "@/components/layout/AppShell"
import { renderWithProviders } from "@/test/render"

// Icon convention for the sidebar: lucide-react icons, which render as
// <svg aria-hidden="true">. A nav link "shows an icon" when it contains an <svg>.
describe("AppShell", () => {
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
})
