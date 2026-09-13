import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { TicketListPage } from "@/pages/TicketListPage"
import {
  filterTickets,
  makeTicket,
  recordSearchParams,
  statusesHandler,
  summaryHandler,
  ticketsHandler,
} from "@/test/handlers"
import { server } from "@/test/msw"
import { renderWithProviders } from "@/test/render"

const fixLogin = makeTicket({ id: 1, title: "Fix login", priority: "urgent", status: "blocked" })
const writeDocs = makeTicket({ id: 2, title: "Write docs", priority: "low", status: null })
const askVendor = makeTicket({
  id: 3,
  title: "Ask vendor",
  priority: "medium",
  status: "needs-help",
  needs_human_eyes: true,
})

// Layout convention: tickets render in a <table>; each ticket is a role="row"
// (plus one header row). Rows are looked up by their accessible name (row text).
//
// Status filter convention: a button named "Filter by status" opens a list of
// checkboxes, one per status from GET /api/statuses, labelled with the status name.
//
// Needs-human-eyes convention: a role="switch" named "Needs human eyes"; every ticket row
// carries data-needs-human-eyes="true|false", and flagged rows contain an alert icon with
// aria-label "Needs human eyes".
//
// Sort convention: a native <select aria-label="Sort by"> whose option values are the API
// sort fields (created_at, updated_at, priority).
describe("TicketListPage", () => {
  beforeEach(() => {
    server.use(ticketsHandler([fixLogin, writeDocs]), statusesHandler(), summaryHandler(0))
  })

  it('lists tickets with title, priority and status chip, showing "no status" when null', async () => {
    renderWithProviders(<TicketListPage />)

    await screen.findByText("Fix login")

    const fixLoginRow = screen.getByRole("row", { name: /fix login/i })
    expect(within(fixLoginRow).getByText(/urgent/i)).toBeInTheDocument()
    expect(within(fixLoginRow).getByText("blocked")).toBeInTheDocument()

    const writeDocsRow = screen.getByRole("row", { name: /write docs/i })
    expect(within(writeDocsRow).getByText(/low/i)).toBeInTheDocument()
    expect(within(writeDocsRow).getByText(/no status/i)).toBeInTheDocument()

    // Header row + two ticket rows, nothing else.
    expect(screen.getAllByRole("row")).toHaveLength(3)
  })

  it("filtering by status sends status query params and shows only returned tickets", async () => {
    const user = userEvent.setup()
    const queries = recordSearchParams("/api/tickets")
    server.use(ticketsHandler(filterTickets([fixLogin, writeDocs])))
    renderWithProviders(<TicketListPage />)

    // Unfiltered: both tickets are shown.
    await screen.findByText("Write docs")
    expect(screen.getByText("Fix login")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /filter by status/i }))
    await user.click(await screen.findByRole("checkbox", { name: "blocked" }))

    // The request MSW received carries the filter...
    await waitFor(() => expect(queries.at(-1)?.getAll("status")).toEqual(["blocked"]))
    // ...and the list shows only what came back.
    await waitFor(() => expect(screen.queryByText("Write docs")).toBeNull())
    expect(screen.getByText("Fix login")).toBeInTheDocument()
  })

  it("multiple statuses can be selected and are sent as repeated params", async () => {
    const user = userEvent.setup()
    const queries = recordSearchParams("/api/tickets")
    server.use(ticketsHandler(filterTickets([fixLogin, writeDocs, askVendor])))
    renderWithProviders(<TicketListPage />)

    await screen.findByText("Write docs")

    await user.click(screen.getByRole("button", { name: /filter by status/i }))
    await user.click(await screen.findByRole("checkbox", { name: "blocked" }))
    await user.click(screen.getByRole("checkbox", { name: "needs-help" }))

    await waitFor(() => expect(queries.at(-1)?.getAll("status")).toEqual(["blocked", "needs-help"]))
    await waitFor(() => expect(screen.queryByText("Write docs")).toBeNull())
    expect(screen.getByText("Fix login")).toBeInTheDocument()
    expect(screen.getByText("Ask vendor")).toBeInTheDocument()
  })

  it("needs-human-eyes toggle sends needs_human_eyes=true and renders alert styling on rows", async () => {
    const user = userEvent.setup()
    const queries = recordSearchParams("/api/tickets")
    server.use(ticketsHandler(filterTickets([fixLogin, askVendor])))
    renderWithProviders(<TicketListPage />)

    // Before toggling: both rows shown, each already marked with its flag state.
    await screen.findByText("Fix login")
    const fixLoginRow = screen.getByRole("row", { name: /fix login/i })
    const askVendorRow = screen.getByRole("row", { name: /ask vendor/i })
    expect(fixLoginRow).toHaveAttribute("data-needs-human-eyes", "false")
    expect(askVendorRow).toHaveAttribute("data-needs-human-eyes", "true")
    expect(within(askVendorRow).getByLabelText(/needs human eyes/i)).toBeInTheDocument()
    expect(within(fixLoginRow).queryByLabelText(/needs human eyes/i)).toBeNull()

    await user.click(screen.getByRole("switch", { name: /needs human eyes/i }))

    await waitFor(() => expect(queries.at(-1)?.get("needs_human_eyes")).toBe("true"))
    await waitFor(() => expect(screen.queryByText("Fix login")).toBeNull())

    const flaggedRow = screen.getByRole("row", { name: /ask vendor/i })
    expect(flaggedRow).toHaveAttribute("data-needs-human-eyes", "true")
    expect(within(flaggedRow).getByLabelText(/needs human eyes/i)).toBeInTheDocument()
  })

  it("sorting by priority sends sort=priority", async () => {
    const user = userEvent.setup()
    const queries = recordSearchParams("/api/tickets")
    renderWithProviders(<TicketListPage />)

    await screen.findByText("Fix login")

    await user.selectOptions(screen.getByRole("combobox", { name: /sort by/i }), "priority")

    await waitFor(() => {
      const last = queries.at(-1)
      expect(last?.get("sort")).toBe("priority")
      expect(last?.get("order")).toBe("desc")
    })
  })
})
