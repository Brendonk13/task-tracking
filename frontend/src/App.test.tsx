import { screen } from "@testing-library/react"
import App from "./App"
import { statusesHandler, summaryHandler, ticketsHandler } from "./test/handlers"
import { server } from "./test/msw"
import { renderWithProviders } from "./test/render"

describe("App", () => {
  beforeEach(() => {
    server.use(summaryHandler(0), ticketsHandler([]), statusesHandler())
  })

  it("home route renders the ticket list page", async () => {
    const home = renderWithProviders(<App />, { route: "/" })

    // The app shell (sidebar navigation) wraps every route...
    expect(screen.getByRole("navigation")).toBeInTheDocument()
    // ...and "/" shows the ticket list page inside it.
    expect(await screen.findByRole("heading", { name: /tickets/i })).toBeInTheDocument()

    // The other nav destination is routed too.
    home.unmount()
    renderWithProviders(<App />, { route: "/sessions" })
    expect(screen.getByRole("navigation")).toBeInTheDocument()
    expect(await screen.findByRole("heading", { name: /sessions/i })).toBeInTheDocument()
  })
})
