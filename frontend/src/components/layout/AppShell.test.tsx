import { screen, within } from "@testing-library/react"
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
})
