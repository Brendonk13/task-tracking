import { screen, within } from "@testing-library/react"
import { TicketListPage } from "@/pages/TicketListPage"
import { makeTicket, statusesHandler, summaryHandler, ticketsHandler } from "@/test/handlers"
import { server } from "@/test/msw"
import { renderWithProviders } from "@/test/render"

// Layout convention: tickets render in a <table>; each ticket is a role="row"
// (plus one header row). Rows are looked up by their accessible name (row text).
describe("TicketListPage", () => {
  beforeEach(() => {
    server.use(
      ticketsHandler([
        makeTicket({ id: 1, title: "Fix login", priority: "urgent", status: "blocked" }),
        makeTicket({ id: 2, title: "Write docs", priority: "low", status: null }),
      ]),
      statusesHandler(),
      summaryHandler(0),
    )
  })

  it('lists tickets with title, priority and status chip, showing "no status" when null', async () => {
    renderWithProviders(<TicketListPage />)

    await screen.findByText("Fix login")

    const fixLogin = screen.getByRole("row", { name: /fix login/i })
    expect(within(fixLogin).getByText(/urgent/i)).toBeInTheDocument()
    expect(within(fixLogin).getByText("blocked")).toBeInTheDocument()

    const writeDocs = screen.getByRole("row", { name: /write docs/i })
    expect(within(writeDocs).getByText(/low/i)).toBeInTheDocument()
    expect(within(writeDocs).getByText(/no status/i)).toBeInTheDocument()

    // Header row + two ticket rows, nothing else.
    expect(screen.getAllByRole("row")).toHaveLength(3)
  })
})
